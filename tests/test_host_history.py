"""Host-origin context never masquerades as signed model activity."""
import copy
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

if sys.version_info >= (3, 14):
    from compression.zstd import decompress as zstd_decompress
else:
    from zstandard import decompress as zstd_decompress

import httpx
import pytest

from eirene.core.compact import compact
from eirene.core.session import Message, Session, export_session, import_session
from eirene.providers import base, registry
from eirene.providers.history import complete_tail, provider_history
from eirene.providers.preflight import validate_history


def request_json(request):
    content = request.content
    if request.headers.get("Content-Encoding") == "zstd":
        content = zstd_decompress(content)
    return json.loads(content)

KEYS = ['chatgpt', 'chatgpt-plan', 'anthropic', 'gemini', 'groq', 'deepseek',
        'kimi', 'ollama', 'ollama-local', 'perplexity', 'omniroute',
        'custom-openai', 'custom-anthropic']


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def sse(*chunks):
    return ''.join('data: ' + json.dumps(c) + '\n\n' for c in chunks)


def recorded(session, *, legacy, failed):
    session.add_user('Inspect the workspace')
    session.add_assistant('Continue the current objective.', host_generated=True)
    call = {'id': 'real', 'name': 'read_file', 'arguments': {'path': 'a.txt'}}
    session.add_assistant('', [call], reasoning_content='Original model reasoning',
        gemini_parts=[{'functionCall': {'name': 'read_file', 'args': {'path': 'a.txt'}}, 'thoughtSignature': 'original-signature'}],
        anthropic_blocks=[{'type': 'thinking', 'thinking': 'Original model reasoning', 'signature': 'original-signature'},
                          {'type': 'tool_use', 'id': 'real', 'name': 'read_file', 'input': {'path': 'a.txt'}}],
        response_items=[{'type': 'reasoning', 'id': 'r', 'encrypted_content': 'original-encrypted', 'summary': []},
                        {'type': 'function_call', 'call_id': 'real', 'name': 'read_file', 'arguments': '{"path":"a.txt"}'}])
    session.add_tool_result('real', 'read_file', 'a.txt contents')
    session.add_assistant('', [{'id': 'background_p', 'name': 'poll_process', 'arguments': {'process_id': 'p'}}],
                          host_generated=not legacy)
    session.add_tool_result('background_p', 'poll_process', 'BACKGROUND_EVIDENCE', failed)


@pytest.mark.parametrize('key', KEYS)
@pytest.mark.parametrize('legacy,failed', [(False, False), (True, True)])
async def test_all_api_providers_keep_background_context_through_lifecycle(key, legacy, failed, config, workdir, monkeypatch):
    config.set_provider(key, api_key='mock-key', base_url='https://mock.invalid/v1')
    provider = registry.build(key, config)
    if key == 'chatgpt-plan':
        monkeypatch.setattr(provider, '_headers', AsyncMock(return_value={'Authorization': 'Bearer mock-key'}))
    session = Session.create(workdir)
    recorded(session, legacy=legacy, failed=failed)
    captures = []
    def respond(request):
        if request.url.path.endswith('/api/show'):
            return httpx.Response(200, json={'model_info': {'llama.context_length': 32768},
                                            'details': {'parameter_size': '70B'}})
        body = request_json(request)
        captures.append(body)
        encoded = json.dumps(body)
        assert 'BACKGROUND_EVIDENCE' in encoded
        assert 'background_p' not in encoded
        assert '"name": "poll_process"' not in encoded
        if provider.protocol == 'gemini':
            parts = [p for c in body['contents'] for p in c['parts']]
            assert [p['thoughtSignature'] for p in parts if 'functionCall' in p] == ['original-signature']
            response = {'candidates': [{'content': {'parts': [{'text': 'Done'}]}, 'finishReason': 'STOP'}]}
        elif provider.protocol == 'anthropic':
            blocks = [p for m in body['messages'] for p in m['content']]
            assert [p['signature'] for p in blocks if p['type'] == 'thinking'] == ['original-signature']
            return httpx.Response(200, text=sse(
                {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'text', 'text': 'Done'}},
                {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}}, {'type': 'message_stop'}))
        elif provider.protocol == 'chatgpt-responses':
            assert any(i.get('encrypted_content') == 'original-encrypted' for i in body['input'])
            return httpx.Response(200, text=sse({'type': 'response.completed', 'response': {
                'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                                                  'content': [{'type': 'output_text', 'text': 'Done'}]}]}}))
        elif provider.protocol == 'ollama':
            assert any(m.get('thinking') == 'Original model reasoning' for m in body['messages'])
            return httpx.Response(200, text=json.dumps({'message': {'content': 'Done'}, 'done': True}) + '\n')
        else:
            if key in {'deepseek', 'kimi', 'custom-openai', 'omniroute'}:
                assert [m['reasoning_content'] for m in body['messages'] if m['role'] == 'assistant'] == ['Original model reasoning']
            if key == 'perplexity':
                assert all(m['role'] != 'tool' and not m.get('tool_calls') for m in body['messages'])
            response = {'choices': [{'delta': {'content': 'Done'}, 'finish_reason': 'stop'}]}
        return httpx.Response(200, text=sse(response))
    base.set_transport(httpx.MockTransport(respond))
    reopened = imported = None
    try:
        for phase in ['active', 'resumed', 'imported', 'compacted']:
            if phase == 'resumed':
                session.close()
                reopened = Session.resume(session.id)
                session = reopened
            elif phase == 'imported':
                export = workdir / 'export.json'
                export_session(session.id, export, 'json')
                imported = import_session(export, workdir)
                session = imported
            elif phase == 'compacted':
                class Summary:
                    async def stream(self, *args, **kwargs):
                        yield base.TextDelta('Continue inspecting the workspace.')
                        yield base.Done()
                await compact(session, Summary(), 'summary-model')
            before = copy.deepcopy(session.messages)
            events = [e async for e in provider.stream(session.messages, 'gemini-3-flash' if key == 'gemini' else 'deepseek-flash')]
            assert isinstance(events[-1], base.Done)
            assert session.messages == before
            validate_history(provider_history(session.messages))
            # The side request takes the same signed history through each API
            # adapter, with its additional task snapshot and no tool schemas.
            from eirene.core.agent import Agent
            from eirene.tools.sandbox import Sandbox
            runner = Agent(session, config, Sandbox(workdir))
            runner.use(provider, key, 'gemini-3-flash' if key == 'gemini' else 'deepseek-flash')
            answer = ''.join([part async for part in runner.aside('What happened so far?')])
            assert answer == 'Done'
            assert 'Session snapshot (untrusted data)' in json.dumps(captures[-1])
            assert session.messages == before
        assert len(captures) == 8
    finally:
        session.close()
        if reopened:
            reopened.close()
        await provider.close()


def test_normalization_is_idempotent_and_preserves_real_background_named_calls(workdir):
    session = Session.create(workdir)
    recorded(session, legacy=True, failed=True)
    history = provider_history(session.messages)
    assert provider_history(history) == history
    real = {'role': 'assistant', 'content': '', 'reasoning_content': 'Real model poll',
            'tool_calls': [{'id': 'background_real', 'name': 'poll_process', 'arguments': {'process_id': 'p'}}]}
    history = [real, Message.tool('background_real', 'poll_process', 'finished')]
    assert provider_history(history) == history
    session.close()


@pytest.mark.parametrize('native', ['claude_code', 'codex_subscription'])
def test_native_handoff_contains_background_and_tool_evidence(native, workdir):
    import importlib
    provider = importlib.import_module('eirene.providers.' + native)
    session = Session.create(workdir)
    recorded(session, legacy=True, failed=True)
    session.add_user('Continue after switching provider')
    text = provider._prior_history(session.messages)
    assert 'BACKGROUND_EVIDENCE' in text and 'a.txt contents' in text
    assert 'Continue after switching provider' not in text
    session.close()


def test_aside_tail_keeps_completed_parallel_group_and_omits_pending_group():
    calls = [{'id': c, 'name': 'read_file', 'arguments': {'path': c}} for c in ['a', 'b', 'c']]
    prefix = [Message.user('Inspect'), Message.assistant('', calls)]
    partial = prefix + [Message.tool('a', 'read_file', 'first result')]
    assert complete_tail(partial, 2) == prefix[:1]
    completed = partial + [Message.tool('b', 'read_file', 'second'), Message.tool('c', 'read_file', 'third')]
    tail = complete_tail(completed, 2)
    assert tail == completed[1:]
    validate_history(tail)


async def test_aside_while_tool_results_are_pending_does_not_mutate_main_session(workdir):
    from test_agent import Script, build
    runner = build(workdir, Script([base.TextDelta('Aside answer'), base.Done()]))
    runner.session.messages = [Message.user('Main goal'), Message.assistant('', [
        {'id': 'pending', 'name': 'read_file', 'arguments': {'path': 'a.txt'}}])]
    before = copy.deepcopy(runner.session.messages)
    _ = [chunk async for chunk in runner.aside('Side question')]
    validate_history(runner.provider.histories[-1])
    assert runner.session.messages == before
    runner.session.close()


def test_process_acknowledgement_requires_saved_owner_and_finished_process(monkeypatch):
    from eirene.tools import processes
    item = SimpleNamespace(id='p', owner='session', running=True, notified=False)
    monkeypatch.setattr(processes, '_processes', {'p': item})
    processes.acknowledge('p', 'session', 'p: running for 1s')
    assert not item.notified
    item.running = False
    processes.acknowledge('p', 'other-session', 'p: exited 0; succeeded')
    assert not item.notified
    processes.acknowledge('p', 'session', 'p: running for 1s')
    assert not item.notified  # Completion raced with saving a still-running poll.
    processes.acknowledge('p', 'session', 'p: exited 0; succeeded')
    assert item.notified
    assert processes.acknowledge('p', 'session', 'p: exited 0; succeeded') is None


async def test_saved_model_poll_updates_original_command_without_synthetic_poll(workdir, config, monkeypatch):
    import time
    from eirene.core.agent import Agent, ToolFinished
    from eirene.core import artifacts
    from eirene.tools import processes
    from eirene.tools.sandbox import Sandbox
    session = Session.create(workdir)
    session.add_user('Run a command')
    session.add_assistant('', [{'id': 'poll', 'name': 'poll_process', 'arguments': {'process_id': 'p'}}])
    artifact = artifacts.Writer()
    artifact.feed('command failed')
    artifact.close()
    item = SimpleNamespace(id='p', owner=session.id, running=False, notified=False,
                           call_id='original-command', command='echo result', cwd=workdir, state='failed',
                           started=time.monotonic(), artifact=artifact, background=True, service=False)
    monkeypatch.setattr(processes, '_processes', {'p': item})
    monkeypatch.setattr(processes, 'poll', AsyncMock(return_value='p: exited 1; failed\ncommand failed'))
    runner = Agent(session, config, Sandbox(workdir))
    try:
        events = [e async for e in runner._handle(base.ToolCall('poll', 'poll_process', {'process_id': 'p'}))]
        assert any(isinstance(e, ToolFinished) and e.id == 'original-command' and e.is_error for e in events)
        assert item.notified
        assert not [e async for e in runner._background_completions()]
        assert not any(c['id'].startswith('background_') for m in session.messages for c in m.get('tool_calls') or [])
    finally:
        await runner.close()
        session.close()
