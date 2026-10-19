"""DeepSeek API contracts, including interruptions and capability changes."""
import asyncio
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image

from eirene.core.config import Config
from eirene.core.errors import AuthError, ProviderError, RateLimitError
from eirene.core.session import Message, Session
from eirene.core.usage import estimate_messages
from eirene.providers import base, registry
from eirene.providers.deepseek import DeepSeek, MODELS
from eirene.tools.registry import specs


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def sse(*chunks):
    return ': keep-alive\n\n' + ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks) + 'data: [DONE]\n\n'


def catalog(model='deepseek-flash', **overrides):
    return {'id': model, 'context_window': 1048576, 'max_output_tokens': 393216,
            'input_modalities': ['text', 'image'],
            'effort': {'supported_levels': ['low', 'high', 'max'], 'default_level': 'high'},
            **overrides}


def image(size=(2, 2), fmt='PNG'):
    output = io.BytesIO()
    Image.new('RGB', size, 'red').save(output, format=fmt)
    return {'name': 'image.png', 'mime_type': 'image/png',
            'data': base64.b64encode(output.getvalue()).decode()}


async def test_discovery_updates_agent_context_and_output_limits(config, workdir):
    from eirene.core.agent import Agent
    from eirene.tools.sandbox import Sandbox
    seen = []
    def respond(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={'data': [catalog(context_window=500000, max_output_tokens=32768)]})
    base.set_transport(httpx.MockTransport(respond))
    config.set_provider('deepseek', api_key='mock-key')
    config.set('max_tokens', 393216)
    provider = registry.build('deepseek', config)
    runner = Agent(Session.create(workdir), config, Sandbox(workdir))
    runner.use(provider, 'deepseek', 'deepseek-flash')
    try:
        await runner.compaction_budget()
        await runner.compaction_budget()
        assert seen == ['/v1/models']
        assert runner.context_limit() == 500000
        assert runner.max_tokens == 32768
        config.set('model_context_limits', {'deepseek-flash': 250000})
        assert runner.context_limit() == 250000
        assert provider._body([Message.user('Hello')], 'deepseek-flash', '', None, 999999)['max_tokens'] == 32768
    finally:
        await runner.close()
        runner.session.close()


async def test_discovery_outage_uses_current_fallback_once():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(503, json={'error': {'message': 'overloaded'}})
    base.set_transport(httpx.MockTransport(respond))
    provider = DeepSeek('key')
    assert await provider.models() == sorted(MODELS)  # Registry fallback order is already sorted.
    assert await provider.resolve_context_window('deepseek-flash') == 1048576
    assert await provider.resolve_context_window('deepseek-flash') == 1048576
    assert len(calls) == 2
    assert registry.default_model('deepseek') == 'deepseek-flash'
    await provider.close()


async def test_discovery_auth_error_is_not_hidden():
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(401)))
    with pytest.raises(AuthError):
        await DeepSeek('bad').resolve_context_window('deepseek-flash')


@pytest.mark.parametrize('effort', ['default', 'none', 'low', 'high', 'max'])
async def test_thinking_controls_and_isolated_requests_do_not_mutate_main(effort):
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=sse({'choices': [{'delta': {'content': 'Done'}, 'finish_reason': 'stop'}]}))
    base.set_transport(httpx.MockTransport(respond))
    provider = DeepSeek('key', reasoning_efforts={'deepseek-flash': effort})
    try:
        for stream in (provider.stream, provider.isolated_stream, provider.stream):
            _ = [e async for e in stream([Message.user('Hello')], 'deepseek-flash', max_tokens=1024)]
        assert requests[0] == requests[2]
        if effort == 'default':
            assert 'thinking' not in requests[0] and 'reasoning_effort' not in requests[0]
        else:
            assert requests[0]['thinking']['type'] == ('disabled' if effort == 'none' else 'enabled')
            assert requests[0].get('reasoning_effort') == (None if effort == 'none' else effort)
        assert requests[1]['thinking'] == {'type': 'disabled'}
        assert requests[1]['max_tokens'] == 1024
    finally:
        await provider.close()


async def test_reasoning_picker_uses_catalog_and_saves_choice(config):
    from eirene.commands.connect import _choose_model
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, json={
        'data': [catalog(effort={'supported_levels': ['high', 'max']})]})))
    provider = DeepSeek('key')
    choices = []
    async def choose(title, options, **kwargs):
        choices.append(options)
        return 'deepseek-flash' if title.startswith('model for') else 'max'
    app = SimpleNamespace(config=config, ask_choice=choose)
    assert await _choose_model(app, provider, 'deepseek') == 'deepseek-flash'
    assert [o[0] for o in choices[1]] == ['default', 'none', 'high', 'max']
    config.save()
    reloaded = Config.load(config.path)
    reloaded.set_provider('deepseek', api_key='key')
    rebuilt = registry.build('deepseek', reloaded)
    assert rebuilt._body([Message.user('Hello')], 'deepseek-flash', '', None, 1024)['reasoning_effort'] == 'max'
    await provider.close()


@pytest.mark.parametrize('finish', ['insufficient_system_resource', 'aborted'])
async def test_interrupted_generation_never_releases_tool_calls(finish):
    body = sse({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c', 'function': {
        'name': 'write_file', 'arguments': '{"path":"a.txt","content":"partial"}'}}]}, 'finish_reason': finish}]})
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    events = []
    with pytest.raises(ProviderError, match=finish) as caught:
        async for event in DeepSeek('key').stream([Message.user('Write')], 'deepseek-flash'):
            events.append(event)
    assert caught.value.retryable
    assert not any(isinstance(e, (base.ToolCall, base.Done)) for e in events)


async def test_truncated_malformed_arguments_are_not_repaired_or_executed():
    body = sse({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c', 'function': {
        'name': 'write_file', 'arguments': '{"path":"unterminated'}}]}, 'finish_reason': 'length'}]})
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    events = [e async for e in DeepSeek('key').stream([Message.user('Write')], 'deepseek-flash')]
    assert events[-1].reason == 'length'
    assert not any(isinstance(e, base.ToolCall) for e in events)


async def test_fragmented_parallel_tools_reasoning_keepalive_and_final_usage():
    body = sse(
        {'choices': [{'delta': {'role': 'assistant', 'content': None, 'reasoning_content': ''}}], 'usage': None},
        {'choices': [{'delta': {'reasoning_content': 'Check '}}]},
        {'choices': [{'delta': {'reasoning_content': 'both', 'tool_calls': [
            {'index': 1, 'id': 'b', 'function': {'name': 'read_file', 'arguments': '{"path":'}},
            {'index': 0, 'id': 'a', 'function': {'name': 'read_file', 'arguments': '{"path":"a'}}]}}]},
        {'choices': [{'delta': {'tool_calls': [
            {'index': 0, 'function': {'arguments': '.txt"}'}},
            {'index': 1, 'function': {'arguments': '"b.txt"}'}}]}}]},
        {'choices': [{'delta': {}, 'finish_reason': 'tool_calls'}], 'usage': {
            'prompt_tokens': 100, 'completion_tokens': 20, 'prompt_cache_hit_tokens': 80,
            'prompt_cache_miss_tokens': 20, 'completion_tokens_details': {'reasoning_tokens': 10}}})
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    events = [e async for e in DeepSeek('key').stream([Message.user('Read')], 'deepseek-flash')]
    calls = [e for e in events if isinstance(e, base.ToolCall)]
    assert [(c.id, c.arguments) for c in calls] == [('a', {'path': 'a.txt'}), ('b', {'path': 'b.txt'})]
    assert [e for e in events if isinstance(e, base.Usage)] == [base.Usage(100, 20)]
    assert events[-1] == base.Done('tool_use', reasoning_content='Check both')


@pytest.mark.parametrize('status,retryable', [(400, False), (401, False), (402, False), (422, False), (429, True), (500, True), (503, True)])
async def test_documented_http_errors(status, retryable):
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(
        status, json={'error': {'message': 'provider detail'}}, headers={'retry-after': '1'})))
    with pytest.raises(ProviderError) as caught:
        _ = [e async for e in DeepSeek('key').stream([Message.user('Hi')], 'deepseek-flash')]
    assert caught.value.status == status
    assert caught.value.retryable is retryable
    if status == 429:
        assert isinstance(caught.value, RateLimitError) and caught.value.retry_after == 1


@pytest.mark.parametrize('model', ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-v4-flash-vision-exp'])
def test_flash_images_use_user_content_and_count_toward_context(model):
    history = [Message.user('Describe', [image()])]
    body = DeepSeek('key')._body(history, model, '', specs(), 1024)
    assert body['messages'][0]['content'][1]['type'] == 'image_url'
    assert estimate_messages(history) >= 1024


def test_pro_images_fail_locally_and_tool_names_are_validated():
    provider = DeepSeek('key')
    with pytest.raises(ProviderError, match='does not accept images'):
        provider._body([Message.user('Describe', [image()])], 'deepseek-v4-pro', '', None, 1024)
    with pytest.raises(ProviderError, match='unique tool names'):
        provider._body([Message.user('Hi')], 'deepseek-flash', '', [specs()[0], specs()[0]], 1024)


@pytest.mark.parametrize('size,count', [((8193, 1), 1), ((4097, 1), 15)])
def test_image_dimensions_respect_multi_image_limits(size, count):
    with pytest.raises(ProviderError, match='pixels per side'):
        DeepSeek('key')._body([Message.user('Describe', [image(size)] * count)], 'deepseek-flash', '', None, 1024)


def test_bad_images_count_and_request_size_are_local_errors(monkeypatch):
    import eirene.providers.deepseek as adapter
    provider = DeepSeek('key')
    with pytest.raises(ProviderError, match='invalid'):
        provider._body([Message.user('Describe', [{'data': 'invalid', 'mime_type': 'image/png'}])], 'deepseek-flash', '', None, 1024)
    with pytest.raises(ProviderError, match='600 images'):
        provider._body([Message.user('Describe', [image()] * 601)], 'deepseek-flash', '', None, 1024)
    monkeypatch.setattr(adapter, 'MAX_REQUEST_BYTES', 100)
    with pytest.raises(ProviderError, match='48 MiB'):
        provider._body([Message.user('x' * 100)], 'deepseek-flash', '', None, 1024)


async def test_pro_image_tool_returns_feedback_without_poisoning_history(workdir, config):
    from eirene.core.agent import Agent, ToolFinished
    from eirene.tools.sandbox import Sandbox
    Image.new('RGB', (2, 2)).save(workdir / 'image.png')
    session = Session.create(workdir)
    session.add_user('Inspect image.png')
    call = {'id': 'image', 'name': 'read_image', 'arguments': {'path': 'image.png'}}
    session.add_assistant('', [call], reasoning_content='Inspect the image')
    runner = Agent(session, config, Sandbox(workdir))
    runner.use(DeepSeek('key'), 'deepseek', 'deepseek-v4-pro')
    try:
        events = [e async for e in runner._handle(base.ToolCall(**call))]
        result = next(e for e in events if isinstance(e, ToolFinished))
        assert result.is_error and 'does not accept images' in result.result
        assert not any(m.get('attachments') for m in session.messages)
        runner.provider._body(session.messages, 'deepseek-v4-pro', '', specs(), 1024)
    finally:
        await runner.close()
        session.close()


async def test_model_reasoning_cancellation_preserves_current_selection(config):
    from eirene.commands.model import _use
    config.provider = 'deepseek'
    config.model = 'deepseek-flash'
    config.set_provider('deepseek', api_key='mock-key')
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, json={'data': [catalog('deepseek-v4-pro')]})))
    app = SimpleNamespace(config=config, ask_choice=AsyncMock(return_value=None), say=lambda *args: None,
                          _save_config=lambda: pytest.fail('must not save cancelled selection'))
    await _use(app, 'deepseek', 'deepseek-v4-pro')
    assert config.model == 'deepseek-flash'


def test_background_polls_become_observations_without_rewriting_real_calls(workdir):
    from eirene.core.session import read_records, replay
    session = Session.create(workdir)
    session.add_user('Run a command')
    session.add_assistant('', [{'id': 'real', 'name': 'run_command', 'arguments': {'command': 'echo ok'}}],
                          reasoning_content='Run once')
    session.add_tool_result('real', 'run_command', 'Still running')
    session.add_assistant('', [{'id': 'background_p', 'name': 'poll_process', 'arguments': {'process_id': 'p'}}])
    session.add_tool_result('background_p', 'poll_process', 'exit 0\nok')
    session.close()
    history = replay(list(read_records(session.path)))
    original = json.dumps(history)
    body = DeepSeek('key')._body(history, 'deepseek-flash', 'instructions', specs(), 1024)
    assert [m['role'] for m in body['messages']] == ['system', 'user', 'assistant', 'tool', 'user']
    assert body['messages'][2]['reasoning_content'] == 'Run once'
    assert body['messages'][2]['tool_calls'][0]['id'] == 'real'
    assert '"process_id": "p"' in body['messages'][-1]['content']
    assert 'exit 0' in body['messages'][-1]['content']
    assert json.dumps(history) == original


async def test_content_filter_does_not_report_success_or_release_tools():
    body = sse({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'c', 'function': {
        'name': 'write_file', 'arguments': '{}'}}]}, 'finish_reason': 'content_filter'}]})
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    events = []
    with pytest.raises(ProviderError, match='content filter') as caught:
        async for e in DeepSeek('key').stream([Message.user('Write')], 'deepseek-flash'):
            events.append(e)
    assert not caught.value.retryable
    assert not any(isinstance(e, (base.ToolCall, base.Done)) for e in events)


@pytest.mark.parametrize('finish,args,call_id', [
    (None, '{}', 'c'), ('tool_calls', '{"path":"a.txt"', 'c'),
    ('tool_calls', '[]', 'c'), ('tool_calls', '{}', ''),
    ('unexpected_status', '{}', 'c'),
])
async def test_incomplete_or_malformed_tools_are_never_released(finish, args, call_id):
    body = sse({'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': call_id, 'function': {
        'name': 'write_file', 'arguments': args}}]}, 'finish_reason': finish}]})
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, text=body)))
    events = []
    with pytest.raises(ProviderError, match='no tools were executed'):
        async for e in DeepSeek('key').stream([Message.user('Write')], 'deepseek-flash'):
            events.append(e)
    assert not any(isinstance(e, (base.ToolCall, base.Done)) for e in events)


async def test_long_mcp_tool_names_round_trip_without_mutating_registry_or_history():
    long_name = 'mcp_server_' + 'namespace.' * 20 + 'read'
    tool = {'name': long_name, 'description': 'Read', 'parameters': {'type': 'object'}}
    history = [Message.user('Read')]
    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        alias = body['tools'][0]['function']['name']
        assert len(alias) <= 128 and '.' not in alias
        if len(requests) == 1:
            return httpx.Response(200, text=sse({'choices': [{'delta': {'tool_calls': [{
                'index': 0, 'id': 'c', 'function': {'name': alias, 'arguments': '{}'}}]}, 'finish_reason': 'tool_calls'}]}))
        assert body['messages'][-2]['tool_calls'][0]['function']['name'] == alias
        return httpx.Response(200, text=sse({'choices': [{'delta': {'content': 'Done'}, 'finish_reason': 'stop'}]}))
    base.set_transport(httpx.MockTransport(respond))
    provider = DeepSeek('key')
    try:
        events = [e async for e in provider.stream(history, 'deepseek-flash', tools=[tool])]
        assert next(e for e in events if isinstance(e, base.ToolCall)).name == long_name
        history.extend([Message.assistant('', [{'id': 'c', 'name': long_name, 'arguments': {}}]),
                        Message.tool('c', long_name, 'Read successfully')])
        _ = [e async for e in provider.stream(history, 'deepseek-flash', tools=[tool])]
        assert tool['name'] == long_name
        assert history[-2]['tool_calls'][0]['name'] == long_name
    finally:
        await provider.close()


async def test_closing_or_cancelling_stream_closes_http_response():
    class Streaming(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"Hello"}}]}\n\n'
            await asyncio.Future()

        async def aclose(self):
            self.closed = True

    for cancel in [False, True]:
        response_stream = Streaming()
        base.set_transport(httpx.MockTransport(lambda r: httpx.Response(200, stream=response_stream)))
        provider = DeepSeek('key')
        stream = provider.stream([Message.user('Hi')], 'deepseek-flash')
        try:
            assert isinstance(await anext(stream), base.TextDelta)
            if cancel:
                task = asyncio.create_task(anext(stream))
                await asyncio.sleep(0)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                await stream.aclose()
            assert response_stream.closed
        finally:
            await stream.aclose()
            await provider.close()
