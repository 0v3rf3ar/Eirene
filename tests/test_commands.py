"""Slash commands, driven through the app."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from eirene.app import Eirene
from eirene.commands import REGISTRY, commands, dispatch
from eirene.core.modes import Mode
from eirene.providers import base, registry
from eirene.providers.base import Done, TextDelta
from eirene.ui.chat import Block, NoticeBlock

EXPECTED = {"help", "connect", "model", "schedule", "tasks", "exit", "usage", "git", "plan", "plugins", "sessions",
            "skills", "compact", "agents", "btw", "clear", "notification", "theme",
            "review", "sandbox", "prompt-suggest"}


class Script:
    supports_tools = True
    protocol = "test"

    def __init__(self, text="hello"):
        self.text = text

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        yield TextDelta(self.text)
        yield Done("stop")

    async def models(self):
        return ["model-a", "model-b"]

    async def validate(self, model=""):
        return "2 models available"


async def start(workdir, provider=None):
    app = Eirene(workdir)
    context = app.run_test(size=(100, 32))
    pilot = await context.__aenter__()
    await pilot.pause()
    if provider is not None:
        app.agent.use(provider, "test", "model-a")
    return app, pilot, context


def texts(app) -> list[str]:
    out = []
    for widget in app.transcript.children:
        if isinstance(widget, (NoticeBlock, Block)):
            body = widget._Static__content
            plain = getattr(body, "plain", None)
            if callable(plain):
                out.append(plain())
            elif plain is not None:
                out.append(plain)
            else:
                out.append(getattr(widget, "buffer", "")
                           or getattr(widget, "raw", ""))
    return out


async def settle(pilot, times=6):
    for _ in range(times):
        await pilot.pause()


def test_every_documented_command_exists():
    names = {command.name for command in commands()}
    assert names == EXPECTED


def test_think_is_only_listed_for_local_ollama(workdir):
    app = Eirene(workdir)
    assert "think" not in {command.name for command in commands(app)}
    app.config.provider = "ollama-local"
    assert "think" in {command.name for command in commands(app)}


def test_every_command_documents_itself():
    for command in commands():
        assert command.summary and command.usage.startswith("/")


async def test_help_lists_every_command(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/help")
        await settle(pilot)
        body = "\n".join(texts(app))
        for name in EXPECTED:
            assert f"/{name}" in body
        assert "shift + tab" in body
        assert "esc" in body
        assert "ctrl + d" in body
        assert "ctrl + ." not in body
        assert "ctrl + c" not in body
    finally:
        await context.__aexit__(None, None, None)


async def test_unknown_command_suggests_a_neighbour(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/hepl")
        await settle(pilot)
        assert any("did you mean /help" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_unknown_command_without_a_match(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/xyzzy")
        await settle(pilot)
        assert any("try /help" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_sessions_picker_switches_the_active_session(workdir):
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("restore this conversation")
    saved.add_assistant("restored answer")
    saved.close()
    app, pilot, context = await start(workdir)
    old_id = app.session.id
    offered = []

    async def ask_choice(title, choices, *, on_highlight=None, **_):
        offered.extend(choices)
        return saved.id

    app.ask_choice = ask_choice
    try:
        await dispatch(app, "/sessions")
        await settle(pilot)
        assert app.session.id == saved.id
        assert app.agent.session is app.session
        assert old_id != app.session.id
        assert any(row[0] == saved.id and saved.id[:8] in row[2]
                   for row in offered)
        assert any("restored answer" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_theme_command_applies_and_persists(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/theme matrix")
        await settle(pilot)
        assert app.theme == "eirene-matrix"
        assert app.config.get("theme") == "matrix"
        assert not any("Matrix theme" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


def test_custom_theme_palettes_have_distinct_bright_roles():
    from eirene.ui.theme import THEMES

    matrix = THEMES["matrix"]
    assert matrix.foreground == "#00ff41"
    assert matrix.accent == "#39ff14"

    hacker = THEMES["hacker-red"]
    assert hacker.foreground == "#ff3131"
    assert hacker.accent == "#ff1744"

    gruvbox = THEMES["gruvbox"]
    assert gruvbox.foreground == "#ebdbb2"
    assert gruvbox.secondary == "#b8bb26"
    assert gruvbox.accent == "#fe8019"
    assert gruvbox.primary == "#fabd2f"
    assert gruvbox.panel == "#3c3836"


async def test_theme_picker_contains_scrollable_catalog(workdir):
    app, pilot, context = await start(workdir)
    seen = []

    async def ask_choice(title, options, *, on_highlight=None, selected=""):
        seen.append(selected)
        seen.extend(options)
        on_highlight("matrix")
        assert app.theme == "eirene-matrix"
        return "gruvbox"

    app.ask_choice = ask_choice
    try:
        await dispatch(app, "/theme")
        assert seen[0] == "default", "the picker opens on the theme in use"
        seen.pop(0)
        assert len(seen) > 10
        assert any(row[0] == "catppuccin" for row in seen)
        assert all(len(row) == 4 and row[3] for row in seen)
        assert app.theme == "eirene-gruvbox"
    finally:
        await context.__aexit__(None, None, None)


async def test_cancelling_theme_preview_restores_saved_theme(workdir):
    app, pilot, context = await start(workdir)

    async def ask_choice(title, options, *, on_highlight=None, **_):
        on_highlight("hacker-red")
        assert app.theme == "eirene-hacker-red"
        return None

    app.ask_choice = ask_choice
    try:
        await dispatch(app, "/theme")
        assert app.theme == "eirene"
        assert app.config.get("theme") == "default"
    finally:
        await context.__aexit__(None, None, None)


async def test_bare_slash_is_handled(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/")
        await settle(pilot)
        assert any("/help" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_a_raising_command_is_caught(workdir):
    app, pilot, context = await start(workdir)

    async def boom(app, args):
        raise RuntimeError("kaboom")

    original = REGISTRY["usage"].handler
    REGISTRY["usage"].handler = boom
    try:
        await dispatch(app, "/usage")
        await settle(pilot)
        assert any("kaboom" in text for text in texts(app))
        assert app.is_running
    finally:
        REGISTRY["usage"].handler = original
        await context.__aexit__(None, None, None)


async def test_agents_switches_mode(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/agents plan")
        await settle(pilot)
        assert app.agent.mode is Mode.PLAN
        assert app.config.mode == "plan"
        await dispatch(app, "/agents auto")
        await settle(pilot)
        assert app.agent.mode is Mode.AUTO
    finally:
        await context.__aexit__(None, None, None)


async def test_agents_rejects_a_bad_mode(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/agents chaos")
        await settle(pilot)
        assert any("no mode called" in text for text in texts(app))
        assert app.agent.mode is Mode.MANUAL
    finally:
        await context.__aexit__(None, None, None)


async def test_usage_before_anything_happens(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/usage")
        await settle(pilot)
        body = app.aside.body._Static__content.plain
        assert "nothing sent yet" in body
        assert app.session.id in body
        assert app.aside.open
        assert not any("nothing sent yet" in text for text in texts(app))

        await pilot.press("escape")
        await pilot.pause()
        assert not app.aside.open
    finally:
        await context.__aexit__(None, None, None)


async def test_usage_counts_a_turn(workdir):
    app, pilot, context = await start(workdir, Script())
    try:
        transcript_before = texts(app)
        app.agent.usage.record(120, 45, 2.0, "model-a")
        await dispatch(app, "/usage")
        await settle(pilot)
        body = app.aside.body._Static__content.plain
        assert "120" in body and "45" in body
        assert texts(app) == transcript_before
    finally:
        await context.__aexit__(None, None, None)


async def test_skills_reports_an_empty_directory(workdir):
    from eirene.core import paths
    app, pilot, context = await start(workdir)
    for stale in paths.skills_dir().glob("*.md"):
        stale.unlink()
    try:
        await dispatch(app, "/skills")
        await settle(pilot)
        assert any("no skills yet" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_btw_needs_a_question(workdir):
    app, pilot, context = await start(workdir, Script())
    try:
        await dispatch(app, "/btw")
        await settle(pilot)
        assert any("give me something to ask" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_btw_answers_without_touching_the_session(workdir):
    app, pilot, context = await start(workdir, Script("forty two"))
    try:
        await dispatch(app, "/btw what is the answer")
        for _ in range(40):
            await pilot.pause()
            if "forty two" in app.aside.answer:
                break
        assert app.aside.open, "the answer belongs in the popup"
        assert "forty two" in app.aside.answer
        assert app.aside.question == "what is the answer"
        assert app.session.messages == []
        assert not app.session.path.exists()
    finally:
        await context.__aexit__(None, None, None)


async def test_btw_works_while_a_turn_is_running(workdir):
    class Slow(Script):
        async def stream(self, messages, model, **kwargs):
            if any(m.get("role") == "user" and "side" in str(m.get("content"))
                   for m in messages):
                yield TextDelta("side answer")
                yield Done("stop")
                return
            yield TextDelta("working")
            await asyncio.sleep(20)

    app, pilot, context = await start(workdir, Slow())
    try:
        app.prompt.value = "long job"
        await pilot.press("enter")
        await pilot.pause()
        assert app.turn is not None and not app.turn.done()
        await dispatch(app, "/btw side question")
        for _ in range(40):
            await pilot.pause()
            if "side answer" in app.aside.answer:
                break
        assert "side answer" in app.aside.answer
        assert not app.turn.done()
        app.turn.cancel()
    finally:
        await context.__aexit__(None, None, None)


async def test_btw_without_a_provider(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/btw hello")
        await settle(pilot)
        assert any("/connect" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_compact_needs_a_provider(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/compact")
        await settle(pilot)
        assert any("/connect" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_compact_shrinks_the_context(workdir):
    app, pilot, context = await start(workdir, Script("a tight summary"))
    try:
        for _ in range(8):
            app.session.add_user("a long question " * 30)
            app.session.add_assistant("a long answer " * 30)
        await dispatch(app, "/compact")
        await settle(pilot, 12)
        body = "\n".join(texts(app))
        assert "→" in body and "saved" in body
        assert len(app.session.messages) < 16
    finally:
        await context.__aexit__(None, None, None)


async def test_model_needs_a_provider(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/model")
        await settle(pilot)
        assert any("/connect" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_model_sets_a_named_model(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.config.provider = "ollama"
        app.config.set_provider("ollama", api_key="ollama-test-key")
        await dispatch(app, "/model llama3:8b")
        await settle(pilot)
        assert app.agent.model == "llama3:8b"
        assert app.config.model == "llama3:8b"
    finally:
        await context.__aexit__(None, None, None)


async def test_think_sets_local_ollama_mode(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.config.provider = "ollama-local"
        app.config.model = "qwen3:8b"
        app.agent.use(registry.build("ollama-local", app.config),
                      "ollama-local", "qwen3:8b")
        await dispatch(app, "/think nothink")
        await settle(pilot)
        assert app.config.provider_config("ollama-local")["think"] is False
        assert app.agent.provider.think is False
        assert any("Ollama mode: nothink" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_connect_rejects_an_unknown_provider(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/connect nonsense")
        await settle(pilot)
        assert any("unknown provider" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_connect_retries_a_bad_key(workdir):
    app, pilot, context = await start(workdir)
    answers = iter(["", "  ", "sk-good-key-value"])
    picks = iter(["model-a"])

    async def ask_text(label, secret=False):
        return next(answers)

    async def ask_choice(title, options, **_):
        return next(picks)

    app.ask_text = ask_text
    app.ask_choice = ask_choice

    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "model-a"}]},
                              headers={"content-type": "application/json"})

    base.set_transport(httpx.MockTransport(handler))
    try:
        await dispatch(app, "/connect chatgpt")
        await settle(pilot, 10)
        body = "\n".join(texts(app))
        assert "key is empty" in body
        assert app.config.api_key("chatgpt") == "sk-good-key-value"
        assert app.config.provider == "chatgpt"
        assert app.agent.model == "model-a"
    finally:
        base.set_transport(None)
        await context.__aexit__(None, None, None)


async def test_connect_reports_a_rejected_key(workdir):
    app, pilot, context = await start(workdir)

    async def ask_text(label, secret=False):
        return "sk-bad-key-value"

    app.ask_text = ask_text

    def handler(request):
        return httpx.Response(401, json={"error": {"message": "bad key"}},
                              headers={"content-type": "application/json"})

    base.set_transport(httpx.MockTransport(handler))
    try:
        await dispatch(app, "/connect chatgpt")
        await settle(pilot, 10)
        assert any("rejected" in text for text in texts(app))
        assert app.config.api_key("chatgpt") is None
    finally:
        base.set_transport(None)
        await context.__aexit__(None, None, None)


async def test_connect_cancels_cleanly(workdir):
    app, pilot, context = await start(workdir)

    async def ask_text(label, secret=False):
        return None

    app.ask_text = ask_text
    try:
        await dispatch(app, "/connect deepseek")
        await settle(pilot)
        assert any("cancelled" in text for text in texts(app))
        assert app.config.provider is None
    finally:
        await context.__aexit__(None, None, None)


async def test_connect_validates_a_custom_base_url(workdir):
    app, pilot, context = await start(workdir)
    urls = iter(["not a url", "https://llm.example.com/v1"])
    keys = iter(["local-key-value"])

    async def ask_text(label, secret=False):
        return next(keys) if secret else next(urls)

    async def ask_choice(title, options, **_):
        return "model-a"

    app.ask_text = ask_text
    app.ask_choice = ask_choice

    def handler(request):
        return httpx.Response(200, json={"data": [{"id": "model-a"}]},
                              headers={"content-type": "application/json"})

    base.set_transport(httpx.MockTransport(handler))
    try:
        await dispatch(app, "/connect custom-openai")
        await settle(pilot, 10)
        body = "\n".join(texts(app))
        assert "must start with http" in body
        assert app.config.base_url("custom-openai") == "https://llm.example.com/v1"
    finally:
        base.set_transport(None)
        await context.__aexit__(None, None, None)


async def test_tasks_when_there_are_none(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/tasks")
        await settle(pilot)
        assert any("no scheduled tasks" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_tasks_lists_what_is_saved(workdir):
    from eirene.scheduling.base import Schedule, Task, save_tasks
    save_tasks([Task(id="t1", name="nightly", prompt="build it",
                     cwd=str(workdir), schedule=Schedule("hourly"))])
    app, pilot, context = await start(workdir)

    async def ask_choice(title, options, **_):
        return None

    app.ask_choice = ask_choice
    try:
        await dispatch(app, "/tasks")
        await settle(pilot)
        body = "\n".join(texts(app))
        assert "nightly" in body and "hourly" in body
    finally:
        await context.__aexit__(None, None, None)


async def test_schedule_rejects_an_unreadable_schedule(workdir):
    app, pilot, context = await start(workdir)
    answers = iter(["do the thing", "my-task", "whenever i feel like it"])

    async def ask_text(label, secret=False):
        return next(answers)

    async def ask_choice(title, options, **_):
        return "custom"

    app.ask_text = ask_text
    app.ask_choice = ask_choice
    try:
        await dispatch(app, "/schedule")
        await settle(pilot)
        assert any("could not read that schedule" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_schedule_can_be_declined(workdir):
    app, pilot, context = await start(workdir)
    answers = iter(["do the thing", "my-task"])
    choices = iter(["hourly", "no"])

    async def ask_text(label, secret=False):
        return next(answers)

    async def ask_choice(title, options, **_):
        return next(choices)

    app.ask_text = ask_text
    app.ask_choice = ask_choice
    try:
        from eirene.scheduling.base import load_tasks
        await dispatch(app, "/schedule")
        await settle(pilot)
        assert any("cancelled" in text for text in texts(app))
        assert load_tasks() == []
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("raw,expected", [
    ("my task", "my-task"), ("Build & Deploy", "Build-Deploy"),
    ("  spaced  out  ", "spaced-out"),
])
def test_task_names_are_cleaned(raw, expected):
    from eirene.commands.schedule import _clean_name
    assert _clean_name(raw) == expected


def test_unusable_task_name_rejected():
    from eirene.commands.schedule import _clean_name
    from eirene.core.errors import CommandError
    with pytest.raises(CommandError):
        _clean_name("///")


async def test_exit_closes_the_app(workdir):
    app, pilot, context = await start(workdir)
    await dispatch(app, "/exit")
    await pilot.pause()
    assert not app.is_running
    await context.__aexit__(None, None, None)


async def test_notification_toggles(workdir, monkeypatch):
    from eirene.core import notify

    sent = []
    monkeypatch.setattr(notify, "available", lambda: True)
    monkeypatch.setattr(notify, "send",
                        lambda title, body="": sent.append((title, body)) or True)

    app, pilot, context = await start(workdir)
    try:
        assert app.config.get("notifications") is False
        await dispatch(app, "/notification")
        await settle(pilot)
        assert app.config.get("notifications") is True
        assert sent

        await dispatch(app, "/notification")
        await settle(pilot)
        assert app.config.get("notifications") is False

        await dispatch(app, "/notification on")
        await settle(pilot)
        assert app.config.get("notifications") is True
        await dispatch(app, "/notification off")
        await settle(pilot)
        assert app.config.get("notifications") is False
    finally:
        await context.__aexit__(None, None, None)


async def test_notification_needs_a_tool(workdir, monkeypatch):
    from eirene.core import notify

    monkeypatch.setattr(notify, "available", lambda: False)
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/notification on")
        await settle(pilot)
        assert app.config.get("notifications") is False
        assert any("no notification tool" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_notification_rejects_nonsense(workdir):
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/notification maybe")
        await settle(pilot)
        assert any("on, off or test" in text for text in texts(app))
    finally:
        await context.__aexit__(None, None, None)


async def test_a_finished_turn_notifies(workdir, monkeypatch):
    from eirene.core import notify

    sent = []
    monkeypatch.setattr(notify, "available", lambda: True)
    monkeypatch.setattr(notify, "send",
                        lambda title, body="": sent.append((title, body)) or True)

    app, pilot, context = await start(workdir, Script("all finished"))
    try:
        app.config.set("notifications", True)
        app.query_one("Prompt").value = "do the thing"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert sent, "a finished turn should notify"
        title, body = sent[-1]
        assert title == "Do the thing"
        assert "all finished" in body
    finally:
        await context.__aexit__(None, None, None)


async def test_no_notification_when_switched_off(workdir, monkeypatch):
    from eirene.core import notify

    sent = []
    monkeypatch.setattr(notify, "available", lambda: True)
    monkeypatch.setattr(notify, "send",
                        lambda title, body="": sent.append(title) or True)

    app, pilot, context = await start(workdir, Script("quietly"))
    try:
        app.query_one("Prompt").value = "hello"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert not sent
    finally:
        await context.__aexit__(None, None, None)


async def test_the_theme_picker_opens_on_the_theme_in_use(workdir):
    from eirene.ui import theme as themes

    app, pilot, context = await start(workdir)
    try:
        for wanted in ("gruvbox", "latte", "nord"):
            app.config.set("theme", wanted)
            app.theme = themes.THEMES[wanted].name
            await pilot.pause()
            app.prompt.value = "/theme"
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause()
                if app.picker.waiting:
                    break
            assert app.picker.waiting, "the picker never opened"
            highlighted = app.picker.options[app.picker.index][0]
            assert highlighted == wanted, f"opened on {highlighted}, not {wanted}"
            await pilot.press("escape")
            await pilot.pause()
    finally:
        await context.__aexit__(None, None, None)


async def test_the_mode_picker_opens_on_the_current_mode(workdir):
    from eirene.core.modes import Mode

    app, pilot, context = await start(workdir)
    try:
        for mode in (Mode.PLAN, Mode.AUTO, Mode.MANUAL):
            app.agent.mode = mode
            app.prompt.value = "/agents"
            await pilot.press("enter")
            for _ in range(40):
                await pilot.pause()
                if app.picker.waiting:
                    break
            assert app.picker.options[app.picker.index][0] == mode.value
            await pilot.press("escape")
            await pilot.pause()
    finally:
        await context.__aexit__(None, None, None)


async def test_a_picker_with_no_match_still_opens_on_the_first_row(workdir):
    app, pilot, context = await start(workdir)
    try:
        rows = [("a", "first", ""), ("b", "second", "")]
        task = asyncio.create_task(app.ask_choice("pick", rows, selected="missing"))
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.index == 0
        await pilot.press("escape")
        await pilot.pause()
        assert await task is None
    finally:
        await context.__aexit__(None, None, None)
