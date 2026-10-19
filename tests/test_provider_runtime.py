"""Pool ownership, shared throttling, and preflight request boundaries."""
import asyncio
import json

import httpx
import pytest

from eirene.core.errors import ProviderError
from eirene.providers import base
from eirene.providers.gemini import Gemini
from eirene.providers.openai_compat import OpenAICompatible
from eirene.providers.preflight import validate_history
from eirene.providers.request_gate import gate_for


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


async def test_http_pool_reused_and_closed_at_teardown():
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200,json={'data':[{'id':'m'}]})))
    provider = OpenAICompatible('key','https://mock.invalid/v1')
    await provider.models()
    first = provider._http_client
    await provider.models()
    assert provider._http_client is first and not first.is_closed
    await provider.close()
    assert first.is_closed
    await provider.models()
    assert provider._http_client is not first
    await provider.close()


async def test_replacing_transport_retires_old_pool():
    provider = OpenAICompatible('key','https://mock.invalid/v1')
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200,json={'data':[{'id':'old'}]})))
    assert await provider.models() == ['old']
    old = provider._http_client
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200,json={'data':[{'id':'new'}]})))
    assert await provider.models() == ['new']
    assert old.is_closed
    await provider.close()


async def test_related_agents_share_throttle_without_sharing_pool():
    a = Gemini('same-key')
    b = Gemini('same-key')
    c = Gemini('different-key')
    assert gate_for(a) is gate_for(b)
    assert gate_for(a) is not gate_for(c)
    assert 'same-key' not in repr(gate_for(a))
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200,json={'models':[{'name':'models/m'}]})))
    await asyncio.gather(a.models(),b.models())
    assert a._http_client is not b._http_client
    await a.close()
    assert not b._http_client.is_closed
    await b.close()
    await c.close()


async def test_rate_limit_cooldown_reaches_other_agent(monkeypatch):
    monkeypatch.setattr('eirene.providers.request_gate.random.uniform', lambda *args: .01)
    a, b = Gemini('same'), Gemini('same')
    gate = gate_for(a)
    gate.observe(httpx.Response(429,headers={'retry-after':'.025'}))
    start = asyncio.get_running_loop().time()
    await gate_for(b).wait()
    assert asyncio.get_running_loop().time() - start >= .025
    assert gate_for(Gemini('other')).until == 0


async def test_cancelled_waiter_does_not_consume_request_slot():
    provider = Gemini('key')
    gate = gate_for(provider)
    for _ in range(4):
        await gate.slots.acquire()
    async def borrow():
        async with provider._client():
            return True
    task = asyncio.create_task(borrow())
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    for _ in range(4):
        gate.slots.release()
    assert await asyncio.wait_for(borrow(),1)
    await provider.close()


@pytest.mark.parametrize('history', [
    [{'role':'tool','tool_call_id':'orphan','content':'x'}],
    [{'role':'assistant','tool_calls':[{'id':'c','name':'read_file','arguments':{}}]}],
    [{'role':'assistant','tool_calls':[{'id':'c','name':'read_file','arguments':{}}]}, {'role':'user','content':'next'}],
    [{'role':'assistant','tool_calls':[{'id':'c','name':'read_file','arguments':{}}]}, {'role':'tool','tool_call_id':'c','name':'write_file'}],
])
async def test_preflight_fails_before_network(history):
    def unexpected(request):
        pytest.fail('invalid history reached the network')
    base.set_transport(httpx.MockTransport(unexpected))
    provider = OpenAICompatible('key','https://mock.invalid/v1')
    with pytest.raises(ProviderError, match='Conversation message'):
        _ = [e async for e in provider.stream(history,'m')]
    await provider.close()


async def test_gemini_lost_original_signature_fails_locally():
    base.set_transport(httpx.MockTransport(lambda r: pytest.fail('unsigned history reached Gemini')))
    messages = [{'role':'user','content':'read'},
                {'role':'assistant','tool_calls':[{'id':'c','name':'read_file','arguments':{}}],
                 'gemini_parts':[{'functionCall':{'name':'read_file','args':{}}}]},
                {'role':'tool','tool_call_id':'c','name':'read_file','content':'hello'}]
    with pytest.raises(ProviderError,match='original thought signature'):
        _ = [e async for e in Gemini('key').stream(messages,'gemini-3-flash')]


def test_preflight_accepts_reused_ids_across_complete_batches():
    messages=[]
    for _ in range(2):
        messages.extend([{'role':'assistant','tool_calls':[{'id':'c','name':'read_file','arguments':{}}]},
                         {'role':'tool','tool_call_id':'c','name':'read_file','content':'hello'}])
    validate_history(messages)


async def test_http_rate_limit_hook_delays_peer_request(monkeypatch):
    monkeypatch.setattr('eirene.providers.request_gate.random.uniform',lambda *args:.01)
    def respond(request):
        if request.url.path.endswith('/models'):
            return httpx.Response(200,json={'models':[{'name':'models/m'}]})
        return httpx.Response(429,json={'error':{'message':'try later'}},headers={'retry-after':'.025'})
    base.set_transport(httpx.MockTransport(respond))
    a,b=Gemini('same'),Gemini('same')
    try:
        with pytest.raises(ProviderError):
            _=[event async for event in a.stream([{'role':'user','content':'hello'}],'m')]
        start=asyncio.get_running_loop().time()
        assert await b.models()==['m']
        assert asyncio.get_running_loop().time()-start>=.025
    finally:
        await a.close()
        await b.close()


async def test_waiting_peers_are_staggered_after_cooldown(monkeypatch):
    monkeypatch.setattr('eirene.providers.request_gate.random.uniform',lambda *args:.01)
    gate=gate_for(Gemini('shared'))
    gate.observe(httpx.Response(429,headers={'retry-after':'0'}))
    admitted=[]
    async def wait():
        await gate.wait()
        admitted.append(asyncio.get_running_loop().time())
    await asyncio.gather(wait(),wait(),wait())
    assert admitted[1]-admitted[0]>=.008
    assert admitted[2]-admitted[1]>=.008


async def test_cancelling_active_stream_closes_response_and_keeps_pool_usable():
    started=asyncio.Event()
    class Stream(httpx.AsyncByteStream):
        closed=False
        async def __aiter__(self):
            started.set()
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            await asyncio.Event().wait()
        async def aclose(self):
            self.closed=True
    stream=Stream()
    def respond(request):
        if request.method=='GET':
            return httpx.Response(200,json={'data':[{'id':'m'}]})
        return httpx.Response(200,stream=stream)
    base.set_transport(httpx.MockTransport(respond))
    provider=OpenAICompatible('key','https://mock.invalid/v1')
    async def consume():
        return [e async for e in provider.stream([{'role':'user','content':'hello'}],'m')]
    task=asyncio.create_task(consume())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed
    assert await provider.models()==['m']
    await provider.close()
