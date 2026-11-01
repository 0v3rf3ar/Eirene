"""/fast: the same model on each provider's faster serving tier."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from eirene.commands import dispatch
from eirene.providers import base
from eirene.providers.anthropic_compat import AnthropicCompatible
from eirene.providers.base import Done, TextDelta
from eirene.providers.chatgpt_plan import ChatGPTPlan
from eirene.providers.claude_code import ClaudeCode
from eirene.providers.codex_subscription import CodexSubscription
from eirene.providers.openai_compat import OpenAICompatible
from eirene.providers.request_gate import gate_for

from test_chatgpt_plan import save_account, sse
from test_providers import ANTHROPIC_STREAM
from test_tui import Script, content, start

MESSAGES = [{"role": "user", "content": "hi"}]
OPENAI_STREAM = (
    'data: {"choices":[{"delta":{"content":"ok"},"finish_reason":"stop"}]}\n\n'
    "data: [DONE]\n\n")


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def recording(*responses):
    """A transport that replays responses in order and keeps every request."""
    seen: list[httpx.Request] = []
    queue = list(responses)

    def handler(request):
        seen.append(request)
        status, body, headers = queue.pop(0) if len(queue) > 1 else queue[0]
        return httpx.Response(status, content=body.encode(),
                              headers={"content-type": "text/event-stream", **headers})
    base.set_transport(httpx.MockTransport(handler))
    return seen


async def drain(provider, model):
    return [event async for event in provider.stream(MESSAGES, model)]


@pytest.mark.parametrize("model, supported, beta", [
    ("claude-opus-5-5", True, False),
    ("claude-opus-5", True, True),
    ("claude-opus-4-8", True, True),
    ("claude-opus-4-8-20260101", True, True),
    ("claude-opus-4-7", False, False),
    ("claude-opus-5-1", False, False),
    ("claude-sonnet-5-5", False, False),
])
async def test_anthropic_sends_speed_fast_only_for_fast_opus(model, supported, beta):
    seen = recording((200, ANTHROPIC_STREAM, {}))
    provider = AnthropicCompatible("sk-ant-x", "https://api.anthropic.com/v1")
    provider.fast = True
    assert provider.fast_supported(model) is supported
    await drain(provider, model)
    body = json.loads(seen[0].content)
    assert ("speed" in body) is supported
    if supported:
        assert body["speed"] == "fast"
    assert ("fast-mode-2026-02-01" in seen[0].headers.get("anthropic-beta", "")) is beta


async def test_anthropic_never_sends_fast_when_off_or_to_a_clone():
    seen = recording((200, ANTHROPIC_STREAM, {}))
    provider = AnthropicCompatible("sk-ant-x", "https://api.anthropic.com/v1")
    await drain(provider, "claude-opus-5-5")
    clone = AnthropicCompatible("key", "https://clone.example/v1", name="custom-anthropic")
    clone.fast = True
    await drain(clone, "claude-opus-5-5")
    assert all("speed" not in json.loads(request.content) for request in seen)


async def test_anthropic_fast_limit_falls_back_to_standard_then_cools_down():
    limited = (429, json.dumps({"type": "error", "error": {
        "type": "rate_limit_error", "message": "fast limit"}}), {"retry-after": "30"})
    seen = recording(limited, (200, ANTHROPIC_STREAM, {}))
    provider = AnthropicCompatible("sk-ant-x", "https://api.anthropic.com/v1")
    provider.fast = True
    events = await drain(provider, "claude-opus-5")
    assert "".join(e.text for e in events if isinstance(e, TextDelta)) == "Sure"
    assert isinstance(events[-1], Done)
    first, retry = (json.loads(request.content) for request in seen)
    assert first["speed"] == "fast" and "speed" not in retry
    assert "anthropic-beta" not in seen[1].headers
    assert provider.fast_cooling and not provider.fast_active("claude-opus-5")
    # Fast limits are separate, so standard requests are not held back.
    assert gate_for(provider).until == 0
    provider._fast_cooldown_until = 0
    assert provider.fast_active("claude-opus-5")


async def test_openai_api_asks_for_the_priority_tier():
    seen = recording((200, OPENAI_STREAM, {}))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1", name="chatgpt")
    provider.fast = True
    await drain(provider, "gpt-5")
    await drain(provider, "gpt-3.5-turbo")
    groq = OpenAICompatible("gsk", "https://api.groq.com/openai/v1", name="groq")
    groq.fast = True
    await drain(groq, "openai/gpt-oss-120b")
    tiers = [json.loads(request.content).get("service_tier") for request in seen]
    assert tiers == ["priority", None, None]


async def test_chatgpt_plan_uses_the_catalogs_fast_tier():
    provider = ChatGPTPlan()
    save_account(provider.auth)
    provider._catalog = {
        "fast-model": {"slug": "fast-model", "service_tiers": [
            {"id": "priority", "name": "Fast", "description": "2x speed"}]},
        "plain-model": {"slug": "plain-model", "service_tiers": []},
    }
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, text=sse(
            {"type": "response.output_text.delta", "delta": "ok"},
            {"type": "response.completed", "response": {"status": "completed", "output": []}}))
    base.set_transport(httpx.MockTransport(handler))
    provider.fast = True
    try:
        assert provider.fast_supported("fast-model")
        assert not provider.fast_supported("plain-model")
        await drain(provider, "fast-model")
        await drain(provider, "plain-model")
        provider.fast = False
        await drain(provider, "fast-model")
    finally:
        await provider.close()
    assert [body.get("service_tier") for body in bodies] == ["priority", None, None]


class FakeCodexServer:
    """Answers just enough of the app-server protocol for one turn."""

    def __init__(self, tiers):
        self.tiers = tiers
        self.turns: list[dict] = []
        self.pending: asyncio.Queue = asyncio.Queue()

    async def request(self, method, params):
        if method == "model/list":
            return {"data": [{"model": name, "serviceTiers": tiers}
                             for name, tiers in self.tiers.items()]}
        if method == "thread/start":
            return {"thread": {"id": "thread-1"}}
        if method == "turn/start":
            self.turns.append(params)
            await self.pending.put({"method": "turn/completed", "params": {
                "threadId": "thread-1", "turn": {"id": "turn-1", "status": "completed"}}})
            return {"turn": {"id": "turn-1"}}
        return {}

    async def notification(self, timeout):
        return await self.pending.get()


async def test_codex_sends_the_listed_fast_tier_per_turn(workdir):
    server = FakeCodexServer({"gpt-fast": [{"id": "priority", "name": "Fast",
                                            "description": "2x speed"}],
                              "gpt-plain": []})
    provider = CodexSubscription()
    provider.set_context(workdir, "auto")

    async def connect():
        return server
    provider._server = connect
    provider.fast = True
    await drain(provider, "gpt-fast")
    await drain(provider, "gpt-plain")
    provider.fast = False
    await drain(provider, "gpt-fast")
    assert [turn.get("serviceTierForTurn") for turn in server.turns] == ["priority", None, None]
    assert await provider.check_fast("gpt-fast")
    assert not await provider.check_fast("gpt-plain")


async def test_claude_code_passes_its_own_fast_mode_setting(workdir, monkeypatch):
    from eirene.providers import claude_code
    launched = []

    async def refuse(*argv, **kwargs):
        launched.append(argv)
        raise OSError("not started in tests")
    monkeypatch.setattr(claude_code.asyncio, "create_subprocess_exec", refuse)
    provider = ClaudeCode()
    provider.set_context(workdir, "auto")
    provider.fast = True
    for model in ("opus", "sonnet"):
        with pytest.raises(Exception):
            await drain(provider, model)
    provider.fast = False
    with pytest.raises(Exception):
        await drain(provider, "opus")

    def setting(argv):
        return json.loads(argv[list(argv).index("--settings") + 1])["fastMode"]
    assert [setting(argv) for argv in launched] == [True, False, False]


class FastScript(Script):
    """A stub provider that offers fast mode on one model."""

    fast = False
    fast_cooling = False

    def fast_supported(self, model):
        return model == "test-model"

    async def check_fast(self, model):
        return self.fast_supported(model)


async def test_fast_command_toggles_and_shows_in_the_mode_line(workdir):
    from eirene.ui.picker import Picker
    provider = FastScript([TextDelta("hi"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        assert not app.config.get("fast_mode")
        assert "fast" not in content(app.mode_line)
        command = asyncio.create_task(dispatch(app, "/fast"))
        await pilot.pause()
        picker = app.query_one(Picker)
        assert picker.waiting and picker.title == "fast"
        assert picker.options[picker.index][0] == "off", "opens on the setting in use"
        await pilot.press("up")
        await pilot.press("enter")
        await command
        await pilot.pause()
        assert app.config.get("fast_mode") is True and provider.fast is True
        assert content(app.mode_line).endswith("· fast")
        await dispatch(app, "/fast off")
        await pilot.pause()
        assert app.config.get("fast_mode") is False and provider.fast is False
        assert "fast" not in content(app.mode_line)
    finally:
        await context.__aexit__(None, None, None)


async def test_a_fast_fallback_is_announced_once(workdir):
    provider = FastScript([TextDelta("hi"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await dispatch(app, "/fast on")
        provider.fast_cooling = True
        app._note_fast_fallback()
        app._note_fast_fallback()
        await pilot.pause()
        notices = [content(block) for block in app.transcript.children]
        assert sum("fast mode limit reached" in note for note in notices) == 1
        assert "fast (cooling down)" in content(app.mode_line)
    finally:
        await context.__aexit__(None, None, None)


async def test_fast_is_listed_only_for_models_with_a_fast_tier(workdir):
    from eirene.commands import commands
    from eirene.commands.help import build
    provider = FastScript([Done("stop")])
    app, pilot, context = await start(workdir, Script([Done("stop")]))
    try:
        names = lambda: {command.name for command in commands(app)}
        assert "fast" not in names(), "a provider without fast tiers"
        app.agent.use(provider, "test", "test-model")
        assert "fast" in names()
        assert "/fast" in build(commands(app)).plain
        app.agent.use(provider, "test", "other-model")
        assert "fast" not in names()
        assert "/fast" not in build(commands(app)).plain
    finally:
        await context.__aexit__(None, None, None)


async def test_typed_fast_on_explains_where_it_works_but_off_always_works(workdir):
    provider = FastScript([Done("stop")])
    app, pilot, context = await start(workdir)
    try:
        app.agent.use(provider, "anthropic", "claude-sonnet-5-5")
        app.config.set("fast_mode", True)
        await dispatch(app, "/fast on")
        await dispatch(app, "/fast")
        await pilot.pause()
        notices = [content(block) for block in app.transcript.children]
        assert sum("has no fast tier" in note and "Opus 5.5" in note
                   for note in notices) == 2, notices
        await dispatch(app, "/fast off")
        assert app.config.get("fast_mode") is False
    finally:
        await context.__aexit__(None, None, None)


async def test_a_catalog_check_lists_fast_once_codex_reports_a_tier(workdir):
    from eirene.commands import commands

    class CatalogScript(FastScript):
        known = False

        def fast_supported(self, model):
            return self.known

        async def check_fast(self, model):
            self.known = True
            return True

    provider = CatalogScript([Done("stop")])
    app, pilot, context = await start(workdir)
    try:
        app.agent.use(provider, "chatgpt-subscription", "gpt-fast")
        assert "fast" not in {command.name for command in commands(app)}
        app.refresh_mode_line()
        await pilot.pause()
        await pilot.pause()
        assert "fast" in {command.name for command in commands(app)}
    finally:
        await context.__aexit__(None, None, None)
