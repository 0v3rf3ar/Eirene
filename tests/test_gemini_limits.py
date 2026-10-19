"""Actionable Google quota errors, retry hints and accurate output notices."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from eirene.core import artifacts
from eirene.core.errors import ProviderError, RateLimitError
from eirene.providers import base
from eirene.providers.gemini import Gemini
from eirene.providers.request_gate import gate_for


def error(*details):
    return {'error': {'code': 429, 'status': 'RESOURCE_EXHAUSTED',
                      'message': 'Quota exceeded for this model', 'details': list(details)}}


def retry(seconds):
    return {'@type': 'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': seconds}


def quota(quota_id, value='50'):
    return {'@type': 'type.googleapis.com/google.rpc.QuotaFailure',
            'violations': [{'quotaId': quota_id, 'quotaValue': value}]}


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


@pytest.mark.parametrize('headers,duration,expected', [
    ({}, '37.25s', 37.25), ({'retry-after': '2'}, '37s', 37),
    ({'retry-after': '40'}, '37s', 40), ({'retry-after': 'invalid'}, '0s', 0),
    ({}, 'NaNs', None), ({}, '-1s', None), ({}, {}, None),
])
def test_google_retry_info_and_header_honor_longest_delay(headers, duration, expected):
    response = httpx.Response(429, json=error(retry(duration)), headers=headers)
    assert base._retry_after(response) == expected


@pytest.mark.parametrize('violation,reason', [
    (quota('GenerateRequestsPerDayPerProjectPerModel'), 'daily quota'),
    (quota('GenerateRequestsPerMinutePerProjectPerModel', '0'), 'No quota'),
])
async def test_unavailable_or_daily_quota_stops_without_retry_or_peer_cooldown(violation, reason):
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(429, json=error(violation, retry('70856s')))))
    provider = Gemini('mock-key')
    try:
        with pytest.raises(ProviderError, match=reason) as caught:
            _ = [e async for e in provider.stream([{'role': 'user', 'content': 'Hello'}], 'model')]
        assert not caught.value.retryable and caught.value.status == 429
        assert 'Google AI Studio' in str(caught.value)
        assert gate_for(provider).until == 0
    finally:
        await provider.close()


async def test_streamed_google_error_updates_shared_cooldown_after_body_read(monkeypatch):
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield json.dumps(error(quota('GenerateRequestsPerMinutePerProjectPerModel'), retry('2.5s'))).encode()
    monkeypatch.setattr('eirene.providers.request_gate.random.uniform', lambda *args: 0)
    base.set_transport(httpx.MockTransport(lambda r: httpx.Response(429, stream=Body())))
    provider = Gemini('mock-key')
    import asyncio
    start = asyncio.get_running_loop().time()
    try:
        with pytest.raises(RateLimitError) as caught:
            _ = [e async for e in provider.stream([{'role': 'user', 'content': 'Hello'}], 'model')]
        assert caught.value.retry_after == 2.5
        assert 'Quota exceeded' in str(caught.value)
        assert gate_for(provider).until >= start + 2.5
    finally:
        await provider.close()


@pytest.mark.parametrize('delay', [0, 2])
async def test_retry_countdown_keeps_actual_failure_reason_and_honors_zero(workdir, monkeypatch, delay):
    from test_agent import Flaky, build
    from eirene.core.agent import Notice
    import eirene.core.agent as agent_mod
    sleep = AsyncMock()
    monkeypatch.setattr(agent_mod.asyncio, 'sleep', sleep)
    runner = build(workdir, Flaky(1, error=RateLimitError('rate limited by Google: minute quota', retry_after=delay)))
    try:
        notices = [e.text async for e in runner._stream() if isinstance(e, Notice)]
        assert notices and all('minute quota' in text for text in notices)
        assert sleep.await_count == delay
    finally:
        await runner.close()
        runner.session.close()


@pytest.mark.parametrize('output', ['complete line\n', 'complete line\n \t\n', 'سلام\u2003\n', '\n \t'])
async def test_shell_whitespace_trimming_does_not_claim_partial_output(workdir, monkeypatch, output):
    from test_agent import Script, build, drive
    from eirene.providers.base import ToolCall, Done, TextDelta
    from eirene.core.agent import ToolFinished
    import eirene.core.agent as agent_mod
    async def execute(*args, on_output=None, **kwargs):
        on_output(output)
        return output.rstrip() or '(no output)'
    monkeypatch.setattr(agent_mod.tools, 'execute', execute)
    provider = Script([ToolCall('cmd', 'run_command', {'command': 'echo complete'}), Done('tool_use')],
                      [TextDelta('Done'), Done()])
    runner = build(workdir, provider)
    try:
        events = await drive(runner)
        result = next(e for e in events if isinstance(e, ToolFinished))
        assert 'partial output' not in result.result and 'read_output' not in result.result
        assert artifacts.read(result.artifact_id) == output
    finally:
        runner.session.close()


def test_artifact_tracks_last_nonwhitespace_across_chunks():
    writer = artifacts.Writer()
    writer.feed('abc\n ')
    writer.feed('\n\t')
    assert writer.content_size == 3
    writer.feed('d\n')
    assert writer.content_size == writer.size - 1
    writer.close()
