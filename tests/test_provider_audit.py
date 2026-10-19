"""Regressions for the provider protocol audit, using deterministic wire responses."""
import json

import httpx
import pytest

from eirene.core.session import Session, export_session, import_session
from eirene.providers import base, registry
from eirene.providers.anthropic_compat import AnthropicCompatible, to_anthropic_messages
from eirene.providers.gemini import Gemini
from eirene.providers.ollama import to_ollama_messages
from eirene.providers.openai_compat import OpenAICompatible


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def sse(*chunks):
    return ''.join('data: ' + json.dumps(chunk) + '\n\n' for chunk in chunks)


@pytest.mark.parametrize('key', ['chatgpt', 'groq', 'deepseek', 'kimi', 'perplexity', 'custom-openai', 'omniroute'])
async def test_openai_provider_contracts(key, config, workdir):
    config.set_provider(key, api_key='mock-api-key', base_url='https://mock.invalid/v1')
    provider = registry.build(key, config)
    requests = []
    def respond(request):
        assert request.headers['authorization'] == 'Bearer mock-api-key'
        assert request.url.path == '/v1/chat/completions'
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=sse(
            {'choices': [{'delta': {'reasoning_content': 'Check '}}]},
            {'choices': [{'delta': {'reasoning_content': 'files'}}]},
            {'choices': [{'delta': {'content': 'Done'}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': {'prompt_tokens': 10, 'completion_tokens': 4}}))
    base.set_transport(httpx.MockTransport(respond))
    history = [{'role': 'user', 'content': 'Check'}]
    events = [e async for e in provider.stream(history, 'model', tools=[{'name':'read_file','parameters':{'type':'object'}}])]
    done = events[-1]
    assert done.reasoning_content == 'Check files'
    session = Session.create(workdir)
    session.add_user('Check')
    session.add_assistant('Done', reasoning_content=done.reasoning_content)
    session.close()
    resumed = Session.resume(session.id)
    try:
        _ = [e async for e in provider.stream(resumed.messages, 'model')]
        assistant = requests[-1]['messages'][-1]
        if key in {'deepseek','kimi','omniroute','custom-openai'}:
            assert assistant['reasoning_content'] == 'Check files'
        else:
            assert 'reasoning_content' not in assistant
        assert ('tools' in requests[0]) == (key != 'perplexity')
        assert ('max_completion_tokens' in requests[0]) == (key in {'chatgpt','groq'})
    finally:
        resumed.close()


@pytest.mark.parametrize('protocol', ['openai', 'anthropic', 'gemini'])
async def test_unfinished_stream_does_not_release_tool_calls(protocol):
    if protocol == 'openai':
        provider = OpenAICompatible('key','https://mock.invalid/v1')
        body = sse({'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'write_file','arguments':'{}'}}]}}]})
    elif protocol == 'anthropic':
        provider = AnthropicCompatible('key','https://mock.invalid/v1')
        body = sse({'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'c','name':'write_file','input':{}}})
    else:
        provider = Gemini('key','https://mock.invalid/v1')
        body = sse({'candidates':[{'content':{'parts':[{'functionCall':{'name':'write_file','args':{}}}]}}]})
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(200,text=body)))
    events = []
    with pytest.raises(Exception, match='before completion'):
        async for event in provider.stream([{'role':'user','content':'Write'}], 'model'):
            events.append(event)
    assert not any(isinstance(e, base.ToolCall) for e in events)


@pytest.mark.parametrize('protocol', ['openai', 'anthropic', 'gemini'])
async def test_token_limit_is_preserved_with_tool_calls(protocol):
    if protocol == 'openai':
        provider = OpenAICompatible('key','https://mock.invalid/v1')
        body = sse({'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','function':{'name':'read_file','arguments':'{}'}}]},'finish_reason':'length'}]})
    elif protocol == 'anthropic':
        provider = AnthropicCompatible('key','https://mock.invalid/v1')
        body = sse({'type':'content_block_start','index':0,'content_block':{'type':'tool_use','id':'c','name':'read_file','input':{}}},
                   {'type':'message_delta','delta':{'stop_reason':'max_tokens'}}, {'type':'message_stop'})
    else:
        provider = Gemini('key','https://mock.invalid/v1')
        body = sse({'candidates':[{'content':{'parts':[{'functionCall':{'name':'read_file','args':{}}}]},'finishReason':'MAX_TOKENS'}]})
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(200,text=body)))
    events = [e async for e in provider.stream([{'role':'user','content':'Read'}], 'model')]
    assert events[-1].reason in {'length','max_tokens'}


async def test_anthropic_signed_thinking_blocks_and_initial_tool_input(workdir):
    chunks = [
        {'type':'content_block_start','index':0,'content_block':{'type':'thinking','thinking':'','signature':''}},
        {'type':'content_block_delta','index':0,'delta':{'type':'thinking_delta','thinking':'Inspect'}},
        {'type':'content_block_delta','index':0,'delta':{'type':'signature_delta','signature':'signed'}},
        {'type':'content_block_start','index':1,'content_block':{'type':'redacted_thinking','data':'opaque'}},
        {'type':'content_block_start','index':2,'content_block':{'type':'tool_use','id':'c','name':'read_file','input':{'path':'a.txt'}}},
        {'type':'message_delta','delta':{'stop_reason':'tool_use'}}, {'type':'message_stop'}]
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200,text=sse(*chunks))))
    events = [e async for e in AnthropicCompatible('key','https://mock.invalid/v1').stream([{'role':'user','content':'Read'}],'model')]
    assert next(e for e in events if isinstance(e,base.ToolCall)).arguments == {'path':'a.txt'}
    blocks = events[-1].anthropic_blocks
    assert blocks[0] == {'type':'thinking','thinking':'Inspect','signature':'signed'}
    assert blocks[1] == {'type':'redacted_thinking','data':'opaque'}
    session = Session.create(workdir)
    session.add_user('Read')
    session.add_assistant('', [{'id':'c','name':'read_file','arguments':{'path':'a.txt'}}], anthropic_blocks=blocks)
    session.add_tool_result('c','read_file','hello')
    session.close()
    export = workdir / 'export.json'
    export_session(session.id, export, 'json')
    imported = import_session(export, workdir)
    loaded = Session.resume(imported.id)
    try:
        assert to_anthropic_messages(loaded.messages)[1]['content'] == blocks
    finally:
        loaded.close()


def test_ollama_images_and_thinking_history():
    history = [{'role':'user','content':'Inspect','attachments':[{'data':'base64-image','mime_type':'image/png'}]},
               {'role':'assistant','content':'Done','reasoning_content':'Check image'}]
    wire = to_ollama_messages(history,'')
    assert wire[0]['images'] == ['base64-image']
    assert wire[1]['thinking'] == 'Check image'


@pytest.mark.parametrize('protocol', ['anthropic', 'gemini'])
async def test_model_discovery_follows_pagination(protocol):
    requests = []
    def respond(request):
        requests.append(request)
        if protocol == 'gemini':
            assert request.headers['x-goog-api-key'] == 'key'
            if len(requests) == 1:
                return httpx.Response(200,json={'models':[{'name':'models/a','supportedGenerationMethods':['generateContent']}], 'nextPageToken':'next'})
            assert request.url.params['pageToken'] == 'next'
            return httpx.Response(200,json={'models':[{'name':'models/b','supportedGenerationMethods':['generateContent']}]})
        assert request.headers['x-api-key'] == 'key'
        if len(requests) == 1:
            return httpx.Response(200,json={'data':[{'id':'a'}], 'has_more':True,'last_id':'a'})
        assert request.url.params['after_id'] == 'a'
        return httpx.Response(200,json={'data':[{'id':'b'}], 'has_more':False})
    base.set_transport(httpx.MockTransport(respond))
    provider = Gemini('key') if protocol == 'gemini' else AnthropicCompatible('key','https://mock.invalid/v1')
    assert set(await provider.models()) == {'a','b'}
    assert len(requests) == 2


async def test_sse_multiline_data_preserves_event_and_empty_lines():
    body = 'event: content_block_delta\ndata: {"type": "content_block_delta",\ndata: "delta": {"type": "text_delta", "text": "hello"}}\n\n: heartbeat\n\ndata: [DONE]\n\n'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,text=body))) as client:
        async with client.stream('GET','https://mock.invalid') as response:
            events = [event async for event in base.sse_lines(response)]
    assert events[0][0] == 'content_block_delta'
    assert json.loads(events[0][1])['delta']['text'] == 'hello'
    assert events[1] == ('', '[DONE]')


@pytest.mark.parametrize('key', ['deepseek', 'kimi'])
async def test_reasoning_survives_agent_tool_loop(key, config, workdir):
    from eirene.core.agent import Agent, Failed, ToolFinished
    from eirene.tools.sandbox import Sandbox
    (workdir / 'a.txt').write_text('hello', encoding='utf-8')
    config.set('mode', 'auto')
    config.set('execution_isolation', 'none')
    config.set_provider(key, api_key='mock-key', base_url='https://mock.invalid/v1')
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            body = sse({'choices':[{'delta':{'reasoning_content':'Read the file'}}]},
                       {'choices':[{'delta':{'tool_calls':[{'index':0,'id':'call','function':{'name':'read_file','arguments':'{"path":"a.txt"}'}}]}, 'finish_reason':'tool_calls'}]})
        else:
            assert requests[-1]['messages'][-2]['reasoning_content'] == 'Read the file'
            assert requests[-1]['messages'][-1]['role'] == 'tool'
            assert 'hello' in requests[-1]['messages'][-1]['content']
            body = sse({'choices':[{'delta':{'content':'Read successfully'},'finish_reason':'stop'}]})
        return httpx.Response(200, text=body)
    base.set_transport(httpx.MockTransport(respond))
    runner = Agent(Session.create(workdir), config, Sandbox(workdir))
    runner.use(registry.build(key, config), key, 'model')
    try:
        events = [e async for e in runner.run('Read a.txt')]
        assert not any(isinstance(e, Failed) for e in events)
        assert any(isinstance(e,ToolFinished) and not e.is_error for e in events)
        assert len(requests) == 2
    finally:
        await runner.close()
        runner.session.close()


async def test_gemini_background_completion_uses_client_signature(workdir, config, monkeypatch):
    """A signed model call followed by an automatic host poll must remain replayable."""
    import time
    from types import SimpleNamespace
    from eirene.core import artifacts
    from eirene.core.agent import Agent
    from eirene.providers.gemini import CLIENT_CALL_SIGNATURE
    from eirene.tools import processes
    from eirene.tools.sandbox import Sandbox

    session = Session.create(workdir)
    session.add_user('Run a command and report its result')
    signed = {'functionCall': {'name': 'run_command', 'args': {'command': 'echo ok'}},
              'thoughtSignature': 'original-model-signature'}
    session.add_assistant('', [{'id':'model-call','name':'run_command','arguments':{'command':'echo ok'}}], gemini_parts=[signed])
    session.add_tool_result('model-call','run_command','process p is running')
    writer = artifacts.Writer()
    writer.feed('exit 0\nok')
    writer.close()
    item = SimpleNamespace(id='p', running=False, state='succeeded', artifact=writer,
                           call_id='model-call', command='echo ok', started=time.monotonic(), notified=False)
    monkeypatch.setattr(processes, 'pending', lambda *args: [item])
    async def poll(*args, **kwargs):
        return 'exit 0\nok'
    monkeypatch.setattr(processes, 'poll', poll)
    runner = Agent(session, config, Sandbox(workdir))
    provider = Gemini('key')
    runner.use(provider, 'gemini', 'model')
    _ = [event async for event in runner._background_completions()]
    assert session.messages[-2]['tool_calls'][0]['id'] == 'background_p'
    assert 'gemini_parts' not in session.messages[-2]
    session.close()
    resumed = Session.resume(session.id)
    def respond(request):
        contents = json.loads(request.content)['contents']
        calls = [part for content in contents for part in content['parts'] if 'functionCall' in part]
        assert calls[0] == signed
        assert calls[1]['functionCall']['name'] == 'poll_process'
        assert calls[1]['thoughtSignature'] == CLIENT_CALL_SIGNATURE
        responses = [part for content in contents for part in content['parts'] if 'functionResponse' in part]
        assert len(responses) == 2
        return httpx.Response(200, text=sse({'candidates':[{'content':{'parts':[{'text':'Completed'}]},'finishReason':'STOP'}]}))
    base.set_transport(httpx.MockTransport(respond))
    try:
        events = [e async for e in provider.stream(resumed.messages,'model')]
        assert events[-1].reason == 'stop'
    finally:
        resumed.close()
        await runner.close()


def test_gemini_keeps_unsigned_parallel_response_parts_unchanged():
    from eirene.providers.gemini import to_gemini_contents, CLIENT_CALL_SIGNATURE
    parts = [{'functionCall':{'name':'read_file','args':{'path':'a'}},'thoughtSignature':'real'},
             {'functionCall':{'name':'read_file','args':{'path':'b'}}}]
    contents = to_gemini_contents([{'role':'assistant','gemini_parts':parts},
                                  {'role':'assistant','tool_calls':[{'id':'legacy','name':'poll_process','arguments':{'process_id':'p'}}]}])
    assert contents[0]['parts'] == parts
    assert contents[1]['parts'][0]['thoughtSignature'] == CLIENT_CALL_SIGNATURE
