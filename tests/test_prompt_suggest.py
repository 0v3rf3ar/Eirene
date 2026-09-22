import asyncio
from types import SimpleNamespace

import pytest

from eirene.commands import dispatch
from eirene.providers.base import TextDelta, Done
from test_tui import start, Script, content


@pytest.mark.parametrize("key", ["tab", "right"])
async def test_optional_suggestion_accepts_without_sending(workdir, monkeypatch, key):
    app, pilot, context = await start(workdir, Script([TextDelta("done"), Done("stop")]))
    calls = []
    async def suggest(request, reply):
        calls.append(request)
        return "Add regression tests for this change."
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        answer = SimpleNamespace(buffer="Implemented the change.")
        app._offer_prompt_suggestion("fix it", answer)
        await pilot.pause()
        assert not calls
        await dispatch(app, "/prompt-suggest on")
        app._offer_prompt_suggestion("fix it", answer)
        await pilot.pause()
        assert calls == ["fix it"]
        assert app.prompt.text == ""
        assert app.prompt.placeholder == "Add regression tests for this change."
        assert not any("Add regression tests" in content(b) for b in app.transcript.children)
        before = list(app.session.messages)
        app.prompt.focus()
        await pilot.press(key)
        await pilot.pause()
        assert app.prompt.text == "Add regression tests for this change."
        assert app.session.messages == before
        assert not app.prompt.placeholder
        await dispatch(app, "/prompt-suggest off")
        assert not app.config.get("prompt_suggest")
    finally:
        await context.__aexit__(None, None, None)


async def test_stale_suggestion_does_not_replace_draft(workdir, monkeypatch):
    app, pilot, context = await start(workdir, Script([Done("stop")]))
    ready = asyncio.Event()
    async def suggest(*args):
        await ready.wait()
        return "Stale suggestion"
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.config.set("prompt_suggest", True)
        app._offer_prompt_suggestion("request", SimpleNamespace(buffer="reply"))
        app.prompt.value = "My own draft"
        await pilot.pause()
        ready.set()
        await pilot.pause()
        assert app.prompt.text == "My own draft"
        assert not app.prompt.prompt_suggestion
        assert not app.prompt.placeholder
    finally:
        ready.set()
        await context.__aexit__(None, None, None)


async def test_completed_turn_offers_suggestion_and_reasoning_stays_in_status(workdir, monkeypatch):
    from eirene.providers.base import ThinkingDelta
    from eirene.ui.chat import ThinkingBlock
    from test_tui import type_line
    app, pilot, context = await start(workdir, Script([
        ThinkingDelta("private reasoning"), TextDelta("Finished."), Done("stop")]))
    phases = []
    original = app.status.set_phase
    def phase(value):
        phases.append(value)
        original(value)
    async def suggest(*args):
        return "Review the tests."
    monkeypatch.setattr(app.status, "set_phase", phase)
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.config.set("prompt_suggest", True)
        await type_line(pilot, "Explain this project")
        for _ in range(30):
            await pilot.pause()
            if app.prompt.prompt_suggestion:
                break
        assert app.prompt.prompt_suggestion == "Review the tests."
        assert "reasoning" in phases
        assert not list(app.transcript.query(ThinkingBlock))
        assert not any("private reasoning" in content(b) for b in app.transcript.children)
        await dispatch(app, "/prompt-suggest off")
        await pilot.pause()
        assert not app.prompt.prompt_suggestion
        assert not app.prompt.placeholder
    finally:
        await context.__aexit__(None, None, None)


async def test_sandbox_opens_popup_without_chat_notice(workdir):
    app, pilot, context = await start(workdir)
    try:
        before = list(app.transcript.children)
        await dispatch(app, "/sandbox")
        await pilot.pause()
        assert app.aside.open
        body = content(app.aside.body)
        assert all(label in body for label in ("Runtime", "Status", "Workspace", "Network"))
        assert list(app.transcript.children) == before
        await pilot.press("escape")
        assert not app.aside.open
    finally:
        await context.__aexit__(None, None, None)


async def test_suggestion_generation_uses_isolated_tool_free_request(workdir):
    class Provider(Script):
        async def isolated_stream(self, messages, model, **kwargs):
            assert kwargs["tools"] is None
            assert kwargs["max_tokens"] == 1024
            yield TextDelta("Write tests\nfor this feature.")
    app, pilot, context = await start(workdir, Provider([Done("stop")]))
    try:
        before = list(app.session.messages)
        assert await app.agent.suggest_prompt("request", "reply") == "Write tests for this feature."
        assert app.session.messages == before
        assert app.agent.provider.calls == 0
    finally:
        await context.__aexit__(None, None, None)


async def test_popup_switch_generates_for_existing_reply(workdir, monkeypatch):
    from textual.widgets import Switch
    app, pilot, context = await start(workdir, Script([Done("stop")]))
    ready = asyncio.Event()
    calls = []
    async def suggest(request, reply):
        calls.append((request, reply))
        await ready.wait()
        return "Add tests for the fix."
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.session.add_user("Fix this bug")
        app.session.add_assistant("The bug is fixed.")
        await dispatch(app, "/prompt-suggest")
        await pilot.pause()
        assert app.aside.open and not app.config.get("prompt_suggest")
        switch = app.aside.query_one("#aside-toggle", Switch)
        await pilot.click(switch)
        await pilot.pause()
        assert app.config.get("prompt_suggest") and switch.value
        assert calls == [("Fix this bug", "The bug is fixed.")]
        assert "Generating" in content(app.aside.body)
        ready.set()
        await pilot.pause()
        assert app.prompt.prompt_suggestion == "Add tests for the fix."
        assert "Ready" in content(app.aside.body)
        # Merely reopening settings must not toggle or regenerate.
        await dispatch(app, "/prompt-suggest")
        await pilot.pause()
        assert switch.value and len(calls) == 1
        await pilot.click(switch)
        await pilot.pause()
        assert not app.config.get("prompt_suggest")
        assert not app.prompt.prompt_suggestion
        assert "Disabled" in content(app.aside.body)
    finally:
        ready.set()
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("failure", ["empty", "error", "timeout"])
async def test_suggestion_failures_are_visible(workdir, monkeypatch, failure):
    app, pilot, context = await start(workdir, Script([Done("stop")]))
    async def suggest(*args):
        if failure == "error":
            raise RuntimeError("provider unavailable")
        if failure == "timeout":
            raise asyncio.TimeoutError()
        return ""
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.session.add_user("request")
        app.session.add_assistant("reply")
        await dispatch(app, "/prompt-suggest on")
        await pilot.pause()
        assert "retry" in content(app.aside.body)
        assert not app.prompt.prompt_suggestion
        assert not any("Prompt suggestion:" in content(b) for b in app.transcript.children)
    finally:
        await context.__aexit__(None, None, None)


async def test_placeholder_is_rendered_but_not_submitted_or_saved(workdir):
    app, pilot, context = await start(workdir, Script([Done("stop")]), size=(60, 30))
    try:
        app.prompt.prompt_suggestion = "Review the implementation and add regression tests for the remaining edge cases."
        app.prompt.focus()
        await pilot.pause()
        assert "Review" in app.prompt.render_line(0).text
        assert app.prompt.size.height > 1
        assert "regression" in "".join(app.prompt.render_line(y).text for y in range(app.prompt.size.height))
        assert app.prompt.text == "" and app.prompt.document.text == ""
        before = list(app.session.messages)
        await pilot.press("enter")
        await pilot.pause()
        assert app.session.messages == before
        assert app.prompt.text == "" and app.prompt.placeholder
        await pilot.press("x")
        await pilot.pause()
        assert app.prompt.text == "x"
        assert not app.prompt.placeholder
    finally:
        await context.__aexit__(None, None, None)


async def test_placeholder_follows_light_and_dark_themes_and_hides_for_secrets(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.prompt_suggestion = "Review this change."
        colours = []
        for name in ("textual-dark", "textual-light"):
            app.theme = name
            await pilot.pause()
            colours.append(app.prompt.get_visual_style("text-area--placeholder").foreground)
            assert "Review" in app.prompt.render_line(0).text
        assert colours[0] != colours[1]
        app.prompt.secret = True
        await pilot.pause()
        assert not app.prompt.placeholder
        assert "Review" not in app.prompt.render_line(0).text
    finally:
        await context.__aexit__(None, None, None)


async def test_suggestion_is_prepared_during_answer_and_revealed_at_completion(workdir, monkeypatch):
    from test_tui import type_line
    started = asyncio.Event()
    release = asyncio.Event()
    class Streaming(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("Here is the explanation so far. ")
            await release.wait()
            yield TextDelta("The final details are now complete.")
            yield Done("stop")
    app, pilot, context = await start(workdir, Streaming())
    async def suggest(*args):
        started.set()
        return "Add regression tests for this behavior."
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.config.set("prompt_suggest", True)
        app._titled = True
        await type_line(pilot, "Explain this behavior")
        await asyncio.wait_for(started.wait(), 2)
        await pilot.pause()
        assert app.turn and not app.turn.done()
        assert "Prepared" in app._suggestion_status
        assert app.prompt.placeholder == ""
        release.set()
        await asyncio.wait_for(app.turn, 2)
        await pilot.pause()
        assert app.prompt.placeholder == "Add regression tests for this behavior."
        assert app.prompt.text == ""
    finally:
        release.set()
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("text,reason", [
    ("Add regression tests for", "stop"),
    ("Add regression tests.", "length"),
    ("A" * 600 + ".", "stop"),
])
async def test_incomplete_or_truncated_suggestion_is_never_shown(workdir, text, reason):
    class Provider(Script):
        async def isolated_stream(self, *args, **kwargs):
            yield TextDelta(text)
            yield Done(reason)
    app, pilot, context = await start(workdir, Provider([Done("stop")]))
    try:
        assert await app.agent.suggest_prompt("request", "reply") == ""
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("name", ["eirene", "eirene-matrix", "textual-dark", "textual-light"])
async def test_placeholder_has_neutral_gray_not_theme_accent(workdir, name):
    app, pilot, context = await start(workdir)
    try:
        app.theme = name
        app.prompt.prompt_suggestion = "Review the complete implementation."
        await pilot.pause()
        colour = app.prompt.get_component_styles("text-area--placeholder").color
        if name == "eirene":
            assert colour.ansi == 8  # Explicit terminal gray, not ansi_default.
        else:
            assert colour.r == colour.g == colour.b
            assert 80 <= colour.r <= 150
    finally:
        await context.__aexit__(None, None, None)


async def test_cancelled_answer_never_reveals_prepared_suggestion(workdir, monkeypatch):
    from test_tui import type_line
    release = asyncio.Event()
    class Streaming(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("Working on the answer.")
            await release.wait()
            yield Done("stop")
    app, pilot, context = await start(workdir, Streaming())
    async def suggest(*args):
        return "Review the tests."
    monkeypatch.setattr(app.agent, "suggest_prompt", suggest)
    try:
        app.config.set("prompt_suggest", True)
        await type_line(pilot, "Explain the change")
        await pilot.pause()
        assert "Prepared" in app._suggestion_status
        app.turn.cancel()
        await asyncio.gather(app.turn, return_exceptions=True)
        await pilot.pause()
        assert not app.prompt.placeholder
        assert app._suggestion_task is None
    finally:
        release.set()
        await context.__aexit__(None, None, None)
