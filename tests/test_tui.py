"""The interface, driven through Textual's pilot."""

from __future__ import annotations

import asyncio

import pytest

from eirene import __version__
from eirene.app import Eirene
from eirene.core.modes import Mode
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.tools import processes
from eirene.ui.chat import (AnswerBlock, ArtBlock, BackToBottom, CommandBlock,
                            NoticeBlock, PromptNavigator, ToolBlock, UserBlock)
from eirene.core.prompt import TITLE_PROMPT
from eirene.ui.composer import ModeLine, PromptRow, Rule
from eirene.ui.tasks import TaskList


class Script:
    """Provider stub for the interface tests."""

    supports_tools = True
    protocol = "test"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = 0

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        events = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        for event in events:
            yield event

    async def models(self):
        return ["test-model"]


async def start(workdir, provider=None, size=(100, 32), resume=""):
    app = Eirene(workdir, resume)
    context = app.run_test(size=size)
    pilot = await context.__aenter__()
    await pilot.pause()
    if provider is not None:
        app.agent.use(provider, "test", "test-model")
        app.refresh_mode_line()
    return app, pilot, context


async def type_line(pilot, text: str) -> None:
    pilot.app.query_one("Prompt").value = text
    await pilot.press("enter")
    await pilot.pause()


def blocks(app, kind):
    return [w for w in app.transcript.children if isinstance(w, kind)]


def content(widget) -> str:
    body = widget._Static__content
    plain = getattr(body, "plain", None)
    if callable(plain):
        return plain()
    if plain is not None:
        return plain
    if isinstance(body, str):
        return body
    return getattr(widget, "buffer", "") or getattr(widget, "raw", "")


async def test_app_starts_with_art_and_compact_session_details(workdir):
    app, pilot, context = await start(workdir)
    try:
        banner = content(blocks(app, ArtBlock)[0])
        assert "session" in banner
        assert app.session.id[:8] in banner
        assert workdir.name in banner
        assert "ctrl+d" in banner
        assert f"v{__version__}" in banner
        drawn = blocks(app, ArtBlock)[0]
        picture = drawn._picture_height()
        assert picture > 0
        details = banner.splitlines()[picture + 1:]
        assert len(details) == 5
        assert "┬" in details[0] and "┴" in details[-1]
        assert all("│" in line for line in details[1:-1])
        assert "Tip:" in "\n".join(details)
    finally:
        await context.__aexit__(None, None, None)


async def test_process_bar_only_appears_for_running_commands(workdir, python_command):
    app, pilot, context = await start(workdir)
    try:
        assert not app.process_bar.display
        command = python_command("import time; time.sleep(10)")
        note = await processes.start(command, workdir)
        process_id = note.split()[1]
        await asyncio.sleep(0.25)
        await pilot.pause()

        assert app.process_bar.display
        assert "1 running command" in content(app.process_bar)

        bar = app.process_bar.region
        await pilot.click(offset=(bar.x + 2, bar.y))
        await pilot.pause()
        assert app.picker.waiting
        assert process_id in content(app.picker)
        assert command in content(app.picker)

        await pilot.press("enter")
        await asyncio.sleep(0.25)
        await pilot.pause()
        assert not app.process_bar.display
    finally:
        await context.__aexit__(None, None, None)


async def test_process_bar_immediately_tracks_normal_shell_commands(workdir, python_command):
    from eirene.tools import shell

    app, pilot, context = await start(workdir)
    try:
        command_text = python_command("import time; time.sleep(10)")
        command = asyncio.create_task(
            shell.run(command_text, workdir, timeout=20, allow_blocked=True))
        await asyncio.sleep(0)
        await pilot.pause()

        assert app.process_bar.display
        assert command_text in shell.active()[0][0]
        assert "1 running command" in content(app.process_bar)

        bar = app.process_bar.region
        await pilot.click(offset=(bar.x + 2, bar.y))
        await pilot.pause()
        assert command_text in content(app.picker)
        await pilot.press("enter")
        await command
        await pilot.pause()
        assert not app.process_bar.display
    finally:
        await context.__aexit__(None, None, None)


async def test_process_bar_can_stop_subscription_provider_commands(workdir):
    from eirene.tools import activity

    stopped = asyncio.Event()

    async def stop():
        stopped.set()

    app, pilot, context = await start(workdir)
    command_id = activity.start_provider_command("Codex: npm test", stop)
    try:
        await pilot.pause()
        assert app.process_bar.display
        bar = app.process_bar.region
        await pilot.click(offset=(bar.x + 2, bar.y))
        await pilot.pause()
        assert command_id in content(app.picker)
        assert "Codex: npm test" in content(app.picker)

        await pilot.press("enter")
        await pilot.pause()
        assert stopped.is_set()
        assert not app.process_bar.display
    finally:
        activity.finish_provider_command(command_id)
        await context.__aexit__(None, None, None)


async def test_banner_scrolls_away_with_the_chat(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert isinstance(app.transcript.children[0], ArtBlock)
        assert app.transcript.region.y == 0, "the transcript owns the whole area"
    finally:
        await context.__aexit__(None, None, None)


async def test_ctrl_e_jumps_back_to_the_end(workdir):
    app, pilot, context = await start(workdir)
    try:
        for index in range(8):
            await app.push(UserBlock(f"prompt {index}"))
            await app.push(NoticeBlock("answer\n" * 5))
        await pilot.pause()
        app.transcript.scroll_home(animate=False)
        await pilot.pause()
        assert app.query_one(BackToBottom).display

        await pilot.press("ctrl+e")
        await pilot.pause()
        assert app.transcript.is_vertical_scroll_end
        assert not app.query_one(BackToBottom).display
    finally:
        await context.__aexit__(None, None, None)


async def test_scrolling_up_shows_centered_navigation(workdir):
    app, pilot, context = await start(workdir, size=(80, 28))
    try:
        for index in range(8):
            await app.push(UserBlock(f"prompt number {index}"))
            await app.push(NoticeBlock("answer\n" * 5))
        await pilot.pause()

        app.transcript.scroll_to(y=app.transcript.max_scroll_y - 5,
                                 animate=False)
        await pilot.pause()
        bottom = app.query_one(BackToBottom)
        prompt = app.query_one(PromptNavigator)
        assert bottom.display
        assert prompt.display
        assert content(bottom) == "↓ Jump to bottom (Ctrl + E)"
        assert abs(bottom.region.center[0] - app.screen.region.center[0]) <= 1
        gap = app.query_one(PromptRow).region.y - bottom.region.bottom
        assert gap == 2, "two lines above the input row"
        assert prompt.region.y == 0
        assert prompt.target is not None
        assert prompt.target.raw in content(prompt)

        await pilot.resize_terminal(55, 24)
        await pilot.pause()
        assert abs(bottom.region.center[0] - app.screen.region.center[0]) <= 1
    finally:
        await context.__aexit__(None, None, None)


async def test_prompt_navigation_tracks_earlier_prompts(workdir):
    app, pilot, context = await start(workdir, size=(70, 24))
    try:
        prompts = []
        for index in range(6):
            prompt = await app.push(UserBlock(f"distinct prompt {index}"))
            prompts.append(prompt)
            await app.push(NoticeBlock("response line\n" * 6))
        await pilot.pause()

        app.transcript.scroll_to_widget(prompts[4], top=True, animate=False)
        await pilot.pause()
        navigator = app.query_one(PromptNavigator)
        later_target = navigator.target
        app.transcript.scroll_to_widget(prompts[2], top=True, animate=False)
        await pilot.pause()
        assert navigator.target is prompts[2]
        assert later_target is not None
        assert navigator.target.virtual_region.y < later_target.virtual_region.y

        navigator.on_click(type("Click", (), {"stop": lambda self: None})())
        await pilot.pause()
        assert abs(app.transcript.scroll_y - prompts[2].virtual_region.y) <= 1
    finally:
        await context.__aexit__(None, None, None)


async def test_back_to_bottom_click_returns_to_latest_message(workdir):
    app, pilot, context = await start(workdir, size=(70, 24))
    try:
        for index in range(8):
            await app.push(UserBlock(f"prompt {index}"))
            await app.push(NoticeBlock("response\n" * 5))
        await pilot.pause()
        app.transcript.scroll_home(animate=False)
        await pilot.pause()

        bottom = app.query_one(BackToBottom)
        assert bottom.display
        bottom.on_click(type("Click", (), {"stop": lambda self: None})())
        await pilot.pause()
        assert app.transcript.is_vertical_scroll_end
        assert not bottom.display
        assert not app.query_one(PromptNavigator).display
    finally:
        await context.__aexit__(None, None, None)


async def test_bottom_dock_is_in_the_right_order(workdir):
    app, pilot, context = await start(workdir)
    try:
        composer = app.query_one("Composer")
        names = [type(child).__name__ for child in composer.children]
        assert names == ["Picker", "PermissionBar", "SlashMenu", "StatusLine",
                         "TaskList", "Rule", "PromptRow", "Rule", "ModeLine"]
        row = [type(child).__name__ for child in app.query_one("PromptRow").children]
        assert row == ["Marker", "Prompt"]
        assert content(app.query_one("Marker")) == "❯"
    finally:
        await context.__aexit__(None, None, None)


async def test_complex_plan_is_a_quiet_live_checklist(workdir):
    provider = Script(
        [ToolCall("p1", "plan_update", {
            "objective": "Ship the feature",
            "steps": [
                {"text": "Find the root cause", "status": "in_progress"},
                {"text": "Implement the fix", "status": "pending"},
                {"text": "Run regression tests", "status": "pending"},
            ],
        }), Done("tool_use")],
        [ToolCall("p2", "plan_set_status", {"index": 1, "status": "completed"}),
         ToolCall("p3", "plan_set_status", {"index": 2, "status": "in_progress"}),
         Done("tool_use")],
        [TextDelta("working on it"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "handle this complex task")
        await settle(app, pilot)

        checklist = app.query_one(TaskList)
        shown = content(checklist)
        assert checklist.display
        assert "✓ Find the root cause" in shown
        assert "→ Implement the fix" in shown
        assert "○ Run regression tests" in shown
        assert not any(card.tool.startswith("plan_")
                       for card in blocks(app, ToolBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_auto_mode_never_turns_prose_into_a_question(workdir):
    provider = Script([TextDelta("Which framework should I use?\n\n- Flask\n- Django"),
                       Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "build it")
        await settle(app, pilot)
        assert not app.picker.waiting
    finally:
        await context.__aexit__(None, None, None)


async def test_mode_line_matches_the_spec(workdir):
    app, pilot, context = await start(workdir)
    try:
        line = content(app.query_one(ModeLine))
        assert "manual mode on" in line
        assert "shift + tab to change mode" in line
    finally:
        await context.__aexit__(None, None, None)


async def test_rules_span_the_terminal(workdir):
    app, pilot, context = await start(workdir, size=(70, 30))
    try:
        for rule in app.query(Rule):
            assert len(content(rule)) == 70
    finally:
        await context.__aexit__(None, None, None)


async def test_layout_follows_a_resize(workdir):
    app, pilot, context = await start(workdir, size=(120, 40))
    try:
        await pilot.resize_terminal(64, 24)
        await pilot.pause()
        for rule in app.query(Rule):
            assert len(content(rule)) == 64
        assert app.query_one("Composer").region.right <= 64
        assert app.transcript.region.height >= 1
    finally:
        await context.__aexit__(None, None, None)


async def test_narrow_terminal_picks_a_banner_that_fits(workdir):
    from rich.cells import cell_len

    app, pilot, context = await start(workdir, size=(40, 24))
    try:
        shown = content(blocks(app, ArtBlock)[0])
        assert all(cell_len(line) <= 40 for line in shown.splitlines())
        assert "session" in shown
    finally:
        await context.__aexit__(None, None, None)


async def test_intro_rules_reflow_without_wrapping_on_resize(workdir):
    from rich.cells import cell_len

    app, pilot, context = await start(workdir, size=(100, 32))
    try:
        banner = blocks(app, ArtBlock)[0]
        before = [line for line in content(banner).splitlines() if "┬" in line][0]
        await pilot.resize_terminal(46, 20)
        await pilot.pause()
        await pilot.pause()

        shown = content(banner).splitlines()
        after = [line for line in shown if "┬" in line][0]
        assert cell_len(after) < cell_len(before)
        assert all(cell_len(line) <= banner.size.width for line in shown)
        rules = [line for line in shown if "┬" in line or "┴" in line]
        assert rules and all(cell_len(line) == banner.size.width for line in rules)
        assert banner.size.height == len(shown), "no line may wrap visually"
    finally:
        await context.__aexit__(None, None, None)


async def test_shift_tab_cycles_modes(workdir):
    app, pilot, context = await start(workdir)
    try:
        notices = len(blocks(app, NoticeBlock))
        assert app.agent.mode is Mode.MANUAL
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.agent.mode is Mode.AUTO
        assert "auto mode on" in content(app.query_one(ModeLine))
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.agent.mode is Mode.PLAN
        await pilot.press("shift+tab")
        await pilot.pause()
        assert app.agent.mode is Mode.MANUAL
        assert app.config.mode == "manual"
        assert len(blocks(app, NoticeBlock)) == notices, (
            "mode changes belong in the mode line")
    finally:
        await context.__aexit__(None, None, None)


async def test_streaming_does_not_pull_a_reader_back_to_bottom(workdir):
    app, pilot, context = await start(workdir, size=(70, 24))
    try:
        for index in range(10):
            await app.push(UserBlock(f"older prompt {index}"))
            await app.push(NoticeBlock("older response\n" * 4))
        answer = AnswerBlock()
        answer.feed("beginning")
        await app.push(answer, live=True)
        await pilot.pause()

        app.transcript.scroll_home(animate=False, immediate=True)
        await pilot.pause()
        position = app.transcript.scroll_y
        answer.feed("\n" + "new streamed line\n" * 12)
        app.transcript.flush_live()
        await pilot.pause()

        assert app.transcript.scroll_y == position
        assert not app.transcript.is_vertical_scroll_end
        assert app.query_one(BackToBottom).display
    finally:
        await context.__aexit__(None, None, None)


async def test_streaming_still_follows_when_reader_is_at_bottom(workdir):
    app, pilot, context = await start(workdir, size=(70, 24))
    try:
        answer = AnswerBlock()
        answer.feed("first line")
        await app.push(answer, live=True)
        await pilot.pause()
        answer.feed("\n" + "growing answer\n" * 30)
        app.transcript.flush_live()
        await pilot.pause()

        assert app.transcript.is_vertical_scroll_end
    finally:
        await context.__aexit__(None, None, None)


async def test_idle_double_esc_asks_before_exit(workdir, monkeypatch):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("escape")
        await pilot.pause()
        assert app.is_running
        notices = [content(b) for b in blocks(app, NoticeBlock)]
        assert any("press esc again" in text for text in notices)

        await pilot.press("escape")
        await pilot.pause()
        assert app.picker.waiting
        assert "exit eirene?" in content(app.picker)
        assert "yes" in content(app.picker) and "no" in content(app.picker)

        await pilot.press("down", "enter")
        await pilot.pause()
        assert app.is_running

        left = []
        monkeypatch.setattr(app, "action_leave", lambda: left.append(True))
        await pilot.press("escape", "escape")
        await pilot.pause()
        assert app.picker.waiting
        await pilot.press("enter")
        await pilot.pause()
        assert left == [True]
    finally:
        await context.__aexit__(None, None, None)


async def test_ctrl_c_and_ctrl_period_never_exit(workdir):
    app, pilot, context = await start(workdir)
    try:
        actions = {b.key: b.action for b in app.BINDINGS}
        assert "ctrl+full_stop" not in actions
        assert actions.get("ctrl+c") == "copy_selection(True)"
        await pilot.press("ctrl+c")
        await pilot.pause()
        assert app.is_running
        assert not any("nothing selected" in content(b)
                       for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_esc_cancels_a_running_turn(workdir):
    class Slow(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("thinking")
            await asyncio.sleep(30)

    app, pilot, context = await start(workdir, Slow())
    try:
        await type_line(pilot, "do something slow")
        await pilot.pause()
        assert app.turn is not None and not app.turn.done()
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause()
            if app.turn.done():
                break
        assert app.turn.cancelled() or app.turn.done()
        assert app.is_running
    finally:
        await context.__aexit__(None, None, None)


async def test_ctrl_d_exits(workdir):
    app, pilot, context = await start(workdir)
    await pilot.press("ctrl+d")
    await pilot.pause()
    assert not app.is_running
    await context.__aexit__(None, None, None)


async def test_a_turn_streams_into_the_transcript(workdir):
    provider = Script([TextDelta("first "), TextDelta("answer"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "hello there")
        for _ in range(30):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert [content(b) for b in blocks(app, UserBlock)][0].endswith("hello there")
        assert "first answer" in content(blocks(app, AnswerBlock)[0])
    finally:
        await context.__aexit__(None, None, None)


async def test_tool_calls_appear_as_cards(workdir):
    provider = Script(
        [ToolCall("c1", "run_command", {"command": "echo made"}), Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "say made")
        for _ in range(60):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        cards = blocks(app, CommandBlock)
        assert cards and "echo made" in content(cards[0])
        assert "made" in content(cards[0])
        assert "Ran(echo made)" in content(cards[0])
        assert not cards[0].is_error
    finally:
        await context.__aexit__(None, None, None)


async def test_command_card_has_running_success_and_error_states(workdir):
    app, pilot, context = await start(workdir)
    try:
        card = CommandBlock("run_command", "pytest -q")
        await app.push(card)
        assert "● Running(pytest -q)" in content(card)

        card.finish("12 passed", False, 2.0)
        card.flush()
        assert "● Ran(pytest -q)" in content(card)
        assert "└ 12 passed" in content(card)

        failed = CommandBlock("run_command", "exit 3")
        await app.push(failed)
        failed.finish("exit 3", True, 1.0)
        failed.flush()
        assert "● Ran(exit 3)" in content(failed)
        assert failed.is_error
    finally:
        await context.__aexit__(None, None, None)


async def test_nonzero_command_exit_makes_the_card_fail(workdir, python_command):
    command = python_command("raise SystemExit(3)")
    provider = Script(
        [ToolCall("c1", "run_command", {"command": command}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "run a failing command")
        for _ in range(60):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        card = blocks(app, CommandBlock)[0]
        assert card.is_error
        assert command in content(card)
    finally:
        await context.__aexit__(None, None, None)


async def test_a_write_appears_as_a_change_card(workdir):
    from eirene.ui.chat import ChangeBlock

    provider = Script(
        [ToolCall("c1", "write_file", {"path": "made.txt", "content": "x"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "make a file")
        for _ in range(60):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        cards = blocks(app, ChangeBlock)
        assert cards, "a write should render as a change"
        assert cards[0].change.path == "made.txt"
        assert cards[0].change.action == "Create"
        assert not blocks(app, ToolBlock)
        assert (workdir / "made.txt").exists()
    finally:
        await context.__aexit__(None, None, None)


async def test_permission_bar_gates_a_write(workdir):
    provider = Script(
        [ToolCall("c1", "write_file", {"path": "gated.txt", "content": "x"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "make a file")
        for _ in range(60):
            await pilot.pause()
            if app.permission.has_class("showing"):
                break
        assert app.permission.has_class("showing")
        assert not (workdir / "gated.txt").exists()
        await pilot.press("n")
        for _ in range(40):
            await pilot.pause()
            if app.turn.done():
                break
        assert not (workdir / "gated.txt").exists()
    finally:
        await context.__aexit__(None, None, None)


async def test_permission_yes_lets_it_through(workdir):
    provider = Script(
        [ToolCall("c1", "write_file", {"path": "allowed.txt", "content": "x"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "make a file")
        for _ in range(60):
            await pilot.pause()
            if app.permission.has_class("showing"):
                break
        await pilot.press("y")
        for _ in range(60):
            await pilot.pause()
            if app.turn.done():
                break
        assert (workdir / "allowed.txt").read_text() == "x"
    finally:
        await context.__aexit__(None, None, None)


async def test_status_line_reports_while_working(workdir):
    class Slow(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("x")
            await asyncio.sleep(5)

    app, pilot, context = await start(workdir, Slow())
    try:
        await type_line(pilot, "work")
        for _ in range(20):
            await pilot.pause()
            if app.status.active:
                break
        text = content(app.status)
        assert "…" in text and "s" in text
        assert app.status.active
        app.turn.cancel()
    finally:
        await context.__aexit__(None, None, None)


async def test_picker_keys_still_work_during_a_command(workdir):
    """A command must not block the message pump."""
    app, pilot, context = await start(workdir)
    try:
        app.agent.mode = Mode.AUTO      # the picker opens on the mode in use
        app.prompt.value = "/agents"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting, "the picker never opened"
        assert app.picker.options[app.picker.index][0] == "auto"
        await pilot.press("down")
        await pilot.press("down")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert not app.picker.waiting
        assert app.agent.mode is Mode.PLAN
        assert app.config.mode == "plan"
    finally:
        await context.__aexit__(None, None, None)


async def test_esc_escapes_an_open_picker(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "/agents"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause()
            if not app.picker.waiting:
                break
        assert not app.picker.waiting
        assert app.is_running
        assert app.prompt.has_focus
    finally:
        await context.__aexit__(None, None, None)


async def test_escape_closes_the_picker(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "/agents"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause()
            if not app.picker.waiting:
                break
        assert not app.picker.waiting
        assert app.agent.mode is Mode.MANUAL
    finally:
        await context.__aexit__(None, None, None)


async def test_typing_still_works_after_a_command(workdir):
    app, pilot, context = await start(workdir)
    try:
        app.prompt.value = "/agents"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause()
            if not app.picker.waiting:
                break
        await pilot.press("h", "i")
        await pilot.pause()
        assert app.prompt.value == "hi"
    finally:
        await context.__aexit__(None, None, None)


async def test_esc_escapes_an_open_permission(workdir):
    provider = Script(
        [ToolCall("c1", "write_file", {"path": "x.txt", "content": "x"}),
         Done("tool_use")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "write a file")
        for _ in range(60):
            await pilot.pause()
            if app.permission.waiting:
                break
        assert app.permission.waiting
        await pilot.press("escape")
        for _ in range(60):
            await pilot.pause()
            if not app.permission.waiting:
                break
        assert not app.permission.waiting
        assert not (workdir / "x.txt").exists()
        assert app.is_running
    finally:
        await context.__aexit__(None, None, None)


async def test_prompts_are_hidden_until_needed(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert app.picker.display is False
        assert app.permission.display is False
    finally:
        await context.__aexit__(None, None, None)


async def test_status_line_is_empty_when_idle(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert content(app.status).strip() == ""
    finally:
        await context.__aexit__(None, None, None)


async def test_prompt_recalls_history(workdir):
    app, pilot, context = await start(workdir)
    try:
        await type_line(pilot, "/help")
        await type_line(pilot, "/usage")
        await pilot.press("up")
        await pilot.pause()
        assert app.prompt.value == "/usage"
        await pilot.press("up")
        await pilot.pause()
        assert app.prompt.value == "/help"
    finally:
        await context.__aexit__(None, None, None)


async def test_session_file_records_the_exchange(workdir):
    provider = Script([TextDelta("recorded"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "say something")
        for _ in range(30):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        body = app.session.path.read_text(encoding="utf-8")
        assert "say something" in body
        assert "recorded" in body
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("theme_colour", ["primary", "accent", "error", "warning"])
async def test_theme_emits_no_colour(workdir, theme_colour):
    app, pilot, context = await start(workdir)
    try:
        theme = app.get_theme("eirene")
        assert getattr(theme, theme_colour) == "ansi_default"
    finally:
        await context.__aexit__(None, None, None)


async def test_no_art_beyond_the_banner(workdir):
    provider = Script([TextDelta("instant"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "quick")
        for _ in range(30):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert len(blocks(app, ArtBlock)) == 1, "only the banner"
    finally:
        await context.__aexit__(None, None, None)


async def test_spinner_stops_when_there_is_no_provider(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert not app.agent.ready
        await type_line(pilot, "who are you")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert not app.status.active, "the spinner must not run forever"
        assert content(app.status).strip() == ""
        assert any("/connect" in content(b) for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_spinner_stops_when_the_provider_errors(workdir):
    from eirene.core.errors import ProviderError

    class Broken(Script):
        async def stream(self, *args, **kwargs):
            raise ProviderError("API key rejected")
            yield

    app, pilot, context = await start(workdir, Broken())
    try:
        await type_line(pilot, "hello")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert not app.status.active
    finally:
        await context.__aexit__(None, None, None)


async def test_reasoning_content_is_never_shown(workdir):
    from eirene.providers.base import ThinkingDelta
    from eirene.ui.chat import ThinkingBlock

    provider = Script([ThinkingDelta("the secret plan"), TextDelta("done"),
                       Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "think about it")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        thoughts = blocks(app, ThinkingBlock)
        assert thoughts, "the reasoning marker should appear"
        assert thoughts[0].buffer == "the secret plan"
        assert all("secret plan" not in content(b) for b in thoughts)
        assert "reasoning" in content(thoughts[0])
    finally:
        await context.__aexit__(None, None, None)


async def test_nothing_is_saved_until_a_real_message(workdir):
    app, pilot, context = await start(workdir)
    try:
        await type_line(pilot, "/usage")
        for _ in range(20):
            await pilot.pause()
            if app.command and app.command.done():
                break
        assert not app.session.path.exists()
    finally:
        await context.__aexit__(None, None, None)
    assert not app.session.path.exists()


async def test_clear_destroys_the_session(workdir):
    from eirene import commands

    provider = Script([TextDelta("kept"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        before = content(blocks(app, ArtBlock)[0])
        await type_line(pilot, "remember this")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert app.session.path.exists()

        await commands.dispatch(app, "/clear")
        await pilot.pause()
        await pilot.pause()
        assert not app.session.path.exists()
        assert app.session.messages == []
        assert not blocks(app, UserBlock)
        banners = blocks(app, ArtBlock)
        assert len(banners) == 1
        assert content(banners[0]) == before
        assert app.session.id[:8] in content(banners[0])
        assert workdir.name in content(banners[0])
        assert not blocks(app, NoticeBlock)
    finally:
        await context.__aexit__(None, None, None)
    assert not app.session.path.exists()


async def test_right_click_copies_the_selection(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.pause()
        await pilot.mouse_down(app.transcript, offset=(2, 1))
        await pilot.hover(app.transcript, offset=(2, 1))
        await pilot.mouse_up(app.transcript, offset=(12, 1))
        await pilot.pause()
        selected = app.screen.get_selected_text()
        assert selected
        await pilot.mouse_down(app.transcript, offset=(6, 1), button=3)
        await pilot.pause()
        assert app.clipboard == selected
    finally:
        await context.__aexit__(None, None, None)


async def test_ctrl_shift_c_copies_the_selection(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.pause()
        await pilot.mouse_down(app.transcript, offset=(2, 1))
        await pilot.hover(app.transcript, offset=(2, 1))
        await pilot.mouse_up(app.transcript, offset=(12, 1))
        await pilot.pause()
        selected = app.screen.get_selected_text()
        await pilot.press("ctrl+shift+c")
        await pilot.pause()
        assert app.clipboard == selected
    finally:
        await context.__aexit__(None, None, None)


async def test_copying_nothing_says_so(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("ctrl+shift+c")
        await pilot.pause()
        assert any("nothing selected" in content(b)
                   for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_clear_refuses_mid_turn(workdir):
    from eirene import commands

    class Slow(Script):
        async def stream(self, messages, model, **kwargs):
            await asyncio.sleep(5)
            yield Done("stop")

    app, pilot, context = await start(workdir, Slow())
    try:
        await type_line(pilot, "hold on")
        await pilot.pause()
        await commands.dispatch(app, "/clear")
        await pilot.pause()
        assert app.session.path.exists()
        assert any("still working" in content(b) for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)



def test_invocation_names_the_program(monkeypatch):
    import sys
    from eirene.app import invocation

    monkeypatch.setattr(sys, "argv", ["./dist/eirene"])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert invocation() == "./dist/eirene"
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "argv", ["/usr/lib/eirene/__main__.py"])
    assert invocation().endswith("-m eirene")


async def leave(app, monkeypatch, workdir):
    """Run the exit path without a real terminal."""
    from eirene import app as app_mod

    monkeypatch.setattr(app_mod, "Eirene", lambda *a, **k: app)
    monkeypatch.setattr(type(app), "run", lambda self: None)
    return app_mod.run(workdir)


async def test_exit_points_at_the_saved_session(workdir, monkeypatch, capsys):
    import sys

    provider = Script([TextDelta("kept"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "remember this")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert app.session.saved
    finally:
        await context.__aexit__(None, None, None)

    monkeypatch.setattr(sys, "argv", ["./eirene"])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert await leave(app, monkeypatch, workdir) == 0
    assert capsys.readouterr().out.strip() == (
        f"to continue this session use: ./eirene --resume {app.session.id}")


async def test_no_hint_when_nothing_was_sent(workdir, monkeypatch, capsys):
    app, pilot, context = await start(workdir)
    try:
        await type_line(pilot, "/usage")
        await pilot.pause()
    finally:
        await context.__aexit__(None, None, None)

    assert not app.session.saved
    assert await leave(app, monkeypatch, workdir) == 0
    assert capsys.readouterr().out == ""


async def test_no_hint_after_a_clear(workdir, monkeypatch, capsys):
    from eirene import commands

    provider = Script([TextDelta("kept"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "remember this")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        await commands.dispatch(app, "/clear")
        await pilot.pause()
    finally:
        await context.__aexit__(None, None, None)

    assert not app.session.saved
    assert await leave(app, monkeypatch, workdir) == 0
    assert capsys.readouterr().out == ""


class Listener(Script):
    """Remembers the turns it was asked to run."""

    def __init__(self, *turns):
        super().__init__(*turns)
        self.seen = []

    async def stream(self, messages, model, *, system="", **kwargs):
        if system != TITLE_PROMPT:
            self.seen.append((list(messages), model))
        async for event in super().stream(messages, model, system=system, **kwargs):
            yield event


def earlier_session(workdir):
    """A finished conversation on disk."""
    from eirene.core.session import Session

    session = Session.create(workdir)
    session.add_user("what is in this folder?")
    session.add_assistant("", [{"id": "c1", "name": "list_dir",
                                "arguments": {"path": "."}}])
    session.add_tool_result("c1", "list_dir", "notes.txt")
    session.add_assistant("just notes.txt")
    session.close()
    return session


async def test_resume_redraws_the_earlier_chat(workdir):
    from eirene.ui.chat import ToolBlock as Card

    saved = earlier_session(workdir)
    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        await pilot.pause()
        assert [content(b) for b in blocks(app, UserBlock)][0].endswith(
            "what is in this folder?")
        assert "just notes.txt" in content(blocks(app, AnswerBlock)[0])
        card = blocks(app, Card)[0]
        assert "list_dir" in content(card) or "." in content(card)
        assert "notes.txt" in content(card)
        assert any("resumed 3 earlier messages" in content(b)
                   for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_resume_redraws_saved_file_diffs(workdir):
    from eirene.core.session import Session
    from eirene.ui.chat import ChangeBlock

    preview = ("--- dist/hello.py\n+++ dist/hello.py\n@@ -1 +1,2 @@\n"
               "-print('old')\n+print('new')\n+print('again')")
    saved = Session.create(workdir)
    saved.add_user("update hello")
    saved.add_assistant("", [{
        "id": "c1", "name": "edit_file",
        "arguments": {"path": "dist/hello.py"}, "label": "dist/hello.py",
        "preview": preview, "action": "Update",
    }])
    saved.add_tool_result("c1", "edit_file", "updated dist/hello.py", seconds=2.0)
    saved.close()

    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        await pilot.pause()
        card = blocks(app, ChangeBlock)[0]
        rendered = content(card)
        assert "Update(dist/hello.py)" in rendered
        assert "print('old')" in rendered
        assert "print('new')" in rendered
        assert "print('again')" in rendered
        assert card.seconds == 2.0 and card.finished
    finally:
        await context.__aexit__(None, None, None)


async def test_resume_redraws_saved_command_state(workdir):
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("run tests")
    saved.add_assistant("", [{
        "id": "c1", "name": "run_command",
        "arguments": {"command": "pytest -q"}, "label": "pytest -q",
    }])
    saved.add_tool_result("c1", "run_command", "12 passed", seconds=3.0)
    saved.close()

    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        await pilot.pause()
        card = blocks(app, CommandBlock)[0]
        assert "● Ran(pytest -q)" in content(card)
        assert "└ 12 passed" in content(card)
        assert card.finished and not card.is_error and card.seconds == 3.0
    finally:
        await context.__aexit__(None, None, None)


async def test_the_banner_stays_above_a_resumed_chat(workdir):
    saved = earlier_session(workdir)
    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        await pilot.pause()
        assert isinstance(app.transcript.children[0], ArtBlock)
        assert saved.id[:8] in content(app.transcript.children[0])
    finally:
        await context.__aexit__(None, None, None)


async def test_a_resumed_session_is_sent_to_the_model(workdir):
    saved = earlier_session(workdir)
    provider = Listener([TextDelta("still here"), Done("stop")])
    app, pilot, context = await start(workdir, provider, resume=saved.id)
    try:
        await type_line(pilot, "and now?")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        sent, _ = provider.seen[0]
        assert [m["role"] for m in sent] == ["user", "assistant", "tool",
                                             "assistant", "user"]
        assert sent[0]["content"] == "what is in this folder?"
        assert sent[2]["content"] == "notes.txt"
        assert sent[-1]["content"] == "and now?"
    finally:
        await context.__aexit__(None, None, None)


async def test_changing_the_model_keeps_the_context(workdir):
    provider = Listener([TextDelta("one"), Done("stop")],
                        [TextDelta("two"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "first question")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break

        app.agent.use(provider, "test", "another-model")
        await type_line(pilot, "second question")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break

        sent, model = provider.seen[1]
        assert model == "another-model"
        assert [m["content"] for m in sent] == ["first question", "one",
                                                "second question"]
    finally:
        await context.__aexit__(None, None, None)


async def test_the_model_command_does_not_drop_the_history(workdir):
    from eirene import commands

    provider = Listener([TextDelta("one"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "keep this")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        app.config.provider = "ollama"
        app.config.set_provider("ollama", api_key="ollama-test-key")
        await commands.dispatch(app, "/model gpt-oss:20b")
        await pilot.pause()
        assert app.agent.model == "gpt-oss:20b"
        assert [m["content"] for m in app.session.messages] == ["keep this", "one"]
    finally:
        await context.__aexit__(None, None, None)


async def test_a_change_card_shows_before_the_permission_prompt(workdir):
    from eirene.ui.chat import ChangeBlock

    (workdir / "code.py").write_text("a = 1\n", encoding="utf-8")
    provider = Script(
        [ToolCall("c1", "edit_file",
                  {"path": "code.py", "old_string": "a = 1",
                   "new_string": "a = 2"}), Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "change it")
        for _ in range(40):
            await pilot.pause()
            if app.permission.waiting:
                break
        assert app.permission.waiting, "it should be asking"
        cards = blocks(app, ChangeBlock)
        assert cards, "the diff must be visible before answering"
        assert cards[0].change.added == 1 and cards[0].change.removed == 1
        await pilot.press("escape")
        for _ in range(40):
            await pilot.pause()
            if app.turn.done():
                break
    finally:
        await context.__aexit__(None, None, None)


async def test_a_failed_change_says_so_on_the_card(workdir):
    from eirene.ui.chat import ChangeBlock

    provider = Script(
        [ToolCall("c1", "edit_file",
                  {"path": "missing.py", "old_string": "a", "new_string": "b"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "edit a missing file")
        for _ in range(60):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        cards = blocks(app, ChangeBlock)
        if cards:
            assert cards[0].is_error
        else:
            assert any("does not exist" in content(b) for b in blocks(app, ToolBlock))
    finally:
        await context.__aexit__(None, None, None)


class Titler(Script):
    """Answers turns, and names the session when asked."""

    def __init__(self, *turns, title="Weekly workout planner"):
        super().__init__(*turns)
        self.title = title
        self.titled = 0

    async def stream(self, messages, model, *, system="", **kwargs):
        if system == TITLE_PROMPT:
            self.titled += 1
            yield TextDelta(self.title)
            yield Done("stop")
            return
        async for event in super().stream(messages, model, system=system, **kwargs):
            yield event


async def settle_title(app, pilot, tries=60):
    for _ in range(tries):
        await pilot.pause()
        if app.turn and app.turn.done() and not app.asides:
            return


async def test_the_model_names_the_session(workdir):
    provider = Titler([TextDelta("here you go"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        from eirene.core.session import name_from

        text = "can you write me a html workout plan for the week"
        await type_line(pilot, text)
        await settle_title(app, pilot)
        assert provider.titled == 1
        assert app.session.name == "Weekly workout planner"
        assert app.session.name != name_from(text)
        assert "can you" not in app.session.name.lower()
    finally:
        await context.__aexit__(None, None, None)


async def test_the_placeholder_is_not_the_raw_input(workdir):
    provider = Titler([TextDelta("ok"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        text = "can you please write me a html workout plan for the whole week"
        await type_line(pilot, text)
        assert app.session.name != text
        assert not app.session.name.startswith("can you")
        await settle_title(app, pilot)
    finally:
        await context.__aexit__(None, None, None)


async def test_the_session_is_named_only_once(workdir):
    provider = Titler([TextDelta("one"), Done("stop")],
                      [TextDelta("two"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "first question")
        await settle_title(app, pilot)
        await type_line(pilot, "second question")
        await settle_title(app, pilot)
        assert provider.titled == 1
    finally:
        await context.__aexit__(None, None, None)


async def test_a_resumed_session_keeps_its_name(workdir):
    saved = earlier_session(workdir)
    saved_name = saved.name
    provider = Titler([TextDelta("more"), Done("stop")])
    app, pilot, context = await start(workdir, provider, resume=saved.id)
    try:
        await type_line(pilot, "carry on")
        await settle_title(app, pilot)
        assert provider.titled == 0
        assert app.session.name == saved_name
    finally:
        await context.__aexit__(None, None, None)


async def test_a_useless_title_is_ignored(workdir):
    provider = Titler([TextDelta("ok"), Done("stop")],
                      title="Sure! " + "padding " * 20)
    app, pilot, context = await start(workdir, provider)
    try:
        from eirene.core.session import name_from

        await type_line(pilot, "build the thing")
        await settle_title(app, pilot)
        assert app.session.name == name_from("build the thing")
    finally:
        await context.__aexit__(None, None, None)


async def test_a_broken_titler_does_not_break_the_turn(workdir):
    class Broken(Script):
        async def stream(self, messages, model, *, system="", **kwargs):
            if system == TITLE_PROMPT:
                raise RuntimeError("no titles today")
            async for event in super().stream(messages, model, system=system,
                                              **kwargs):
                yield event

    app, pilot, context = await start(workdir, Broken(
        [TextDelta("fine"), Done("stop")]))
    try:
        await type_line(pilot, "do a thing")
        await settle_title(app, pilot)
        assert app.is_running
        assert app.session.name == "Do a thing"
        assert "fine" in content(blocks(app, AnswerBlock)[0])
    finally:
        await context.__aexit__(None, None, None)


async def test_a_cut_off_reply_says_so(workdir):
    provider = Script([TextDelta("I'll write it now."), Done("length")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "write a huge file")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        notices = [content(b) for b in blocks(app, NoticeBlock)]
        assert any("ran out of room" in text for text in notices)
    finally:
        await context.__aexit__(None, None, None)


def change_card(workdir, before="a = 1\nb = 2\n", after="a = 1\nb = 22\nc = 3\n"):
    from eirene.tools import files
    from eirene.tools.sandbox import Sandbox
    from eirene.ui.chat import ChangeBlock

    (workdir / "code.py").write_text(before, encoding="utf-8")
    text = files.diff_preview(Sandbox(workdir), "code.py", after)
    return ChangeBlock("code.py", text, "Update")


async def test_the_code_in_a_change_can_be_copied(workdir):
    from textual.geometry import Offset
    from textual.selection import Selection

    app, pilot, context = await start(workdir)
    try:
        card = change_card(workdir)
        await app.push(card)
        await pilot.pause()
        picked = card.get_selection(Selection(Offset(0, 2), Offset(200, 4)))
        assert picked is not None, "a change card must be selectable"
        text, ending = picked
        assert "b = 2" in text
        assert "b = 22" in text
        assert not any(line.strip().startswith(("+", "-"))
                       for line in text.splitlines())
        assert "1 " not in text.splitlines()[0][:4]
    finally:
        await context.__aexit__(None, None, None)


async def test_copying_a_change_reaches_the_clipboard(workdir):
    from textual.geometry import Offset
    from textual.selection import Selection

    app, pilot, context = await start(workdir)
    try:
        card = change_card(workdir)
        await app.push(card)
        await pilot.pause()
        app.screen.selections = {card: Selection(Offset(0, 2), Offset(200, 4))}
        app.action_copy_selection()
        await pilot.pause()
        assert "b = 22" in app.clipboard
        assert "● Update" not in app.clipboard
    finally:
        await context.__aexit__(None, None, None)


async def test_the_change_card_paints_colour(workdir):
    app, pilot, context = await start(workdir)
    try:
        card = change_card(workdir)
        await app.push(card)
        await pilot.pause()
        await pilot.pause()
        found = set()
        region = card.region
        for y in range(region.y, min(region.y + region.height, app.size.height)):
            for x in range(region.x, min(region.x + 40, app.size.width)):
                style = app.screen.get_style_at(x, y)
                if style.color:
                    found.add(style.color.name)
                if style.bgcolor:
                    found.add(style.bgcolor.name)
        assert len(found) > 3, f"the code should be highlighted, saw {found}"
    finally:
        await context.__aexit__(None, None, None)


async def test_deleting_the_slash_closes_the_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("/")
        await pilot.pause()
        assert app.slash.open, "typing / should open the menu"
        assert app.slash.display

        await pilot.press("backspace")
        await pilot.pause()
        assert not app.slash.open, "deleting the / must close the menu"
        assert not app.slash.display
        assert not app.prompt.menu_open
    finally:
        await context.__aexit__(None, None, None)


async def test_backspacing_a_command_narrows_the_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press(*"/comp")
        await pilot.pause()
        assert [name for name, _ in app.slash.matches] == ["compact"]

        await pilot.press("backspace", "backspace", "backspace")
        await pilot.pause()
        names = [name for name, _ in app.slash.matches]
        assert "compact" in names and "clear" in names and "connect" in names
    finally:
        await context.__aexit__(None, None, None)


async def test_clearing_the_whole_draft_closes_the_menu(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press(*"/hel")
        await pilot.pause()
        assert app.slash.open
        for _ in range(4):
            await pilot.press("backspace")
        await pilot.pause()
        assert app.prompt.value == ""
        assert not app.slash.open
    finally:
        await context.__aexit__(None, None, None)


async def test_resumed_arrows_recall_the_old_inputs(workdir):
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("first thing")
    saved.add_assistant("done")
    saved.add_user("second thing")
    saved.add_assistant("done again")
    saved.close()

    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        await pilot.pause()
        assert app.prompt.recent == ["first thing", "second thing"]
        app.prompt.focus()
        await pilot.press("up")
        await pilot.pause()
        assert app.prompt.value == "second thing"
        await pilot.press("up")
        await pilot.pause()
        assert app.prompt.value == "first thing"
        await pilot.press("down")
        await pilot.pause()
        assert app.prompt.value == "second thing"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_fresh_session_starts_with_no_history(workdir):
    app, pilot, context = await start(workdir)
    try:
        assert app.prompt.recent == []
        await pilot.press("up")
        await pilot.pause()
        assert app.prompt.value == ""
    finally:
        await context.__aexit__(None, None, None)


async def test_the_tab_spins_while_the_agent_works(workdir):
    class Held(Script):
        def __init__(self):
            super().__init__()
            self.gate = asyncio.Event()

        async def stream(self, *args, **kwargs):
            yield TextDelta("working")
            await self.gate.wait()
            yield Done("stop")

    provider = Held()
    titles = []
    app, pilot, context = await start(workdir, provider)
    try:
        import eirene.app as app_mod
        original = app_mod.write_terminal_title
        app_mod.write_terminal_title = lambda driver, text: titles.append(text) or True
        try:
            await type_line(pilot, "take a while")
            await pilot.pause()
            assert app._busy
            app._spin_tab()
            app._spin_tab()
            busy = [t for t in titles if not t.startswith("eirene -")]
            assert busy, "the tab should show a spinner while busy"
            assert len(set(busy)) > 1, "the spinner should turn"

            provider.gate.set()
            for _ in range(40):
                await pilot.pause()
                if app.turn and app.turn.done():
                    break
            assert not app._busy
            assert titles[-1].startswith("eirene -")
        finally:
            app_mod.write_terminal_title = original
    finally:
        await context.__aexit__(None, None, None)


async def test_answers_carry_file_icons_on_tool_cards(workdir):
    from eirene.ui import art

    provider = Script(
        [ToolCall("c1", "read_file", {"path": "main.py"}), Done("tool_use")],
        [TextDelta("read it"), Done("stop")])
    (workdir / "main.py").write_text("x = 1\n", encoding="utf-8")
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.AUTO
        await type_line(pilot, "read the file")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        card = blocks(app, ToolBlock)[0]
        assert art.file_icon("main.py") in content(card)
    finally:
        await context.__aexit__(None, None, None)


async def test_write_and_edit_tool_fallbacks_do_not_show_file_icons(workdir):
    from eirene.ui import art

    app, pilot, context = await start(workdir)
    try:
        for tool in ("write_file", "edit_file"):
            card = ToolBlock(tool, "code.py")
            await app.push(card)
            assert art.file_icon("code.py") not in content(card)
    finally:
        await context.__aexit__(None, None, None)


async def test_code_in_an_answer_is_highlighted_and_copyable(workdir):
    from textual.geometry import Offset
    from textual.selection import Selection

    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("Here you go:\n\n```python\ndef go():\n    return 1\n```\n")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()

        colours = set()
        region = block.region
        for y in range(region.y, min(region.y + region.height, app.size.height)):
            for x in range(region.x, min(region.x + 30, app.size.width)):
                style = app.screen.get_style_at(x, y)
                if style.color:
                    colours.add(style.color.name)
        assert len(colours) > 2, f"fenced code should be highlighted, saw {colours}"

        picked = block.get_selection(Selection(Offset(0, 3), Offset(40, 4)))
        assert picked is not None
        assert "def go():" in picked[0]
    finally:
        await context.__aexit__(None, None, None)


async def test_an_old_input_copies_without_the_marker(workdir):
    from textual.geometry import Offset
    from textual.selection import Selection

    app, pilot, context = await start(workdir)
    try:
        block = UserBlock("please build the thing")
        await app.push(block)
        await pilot.pause()
        picked = block.get_selection(Selection(Offset(0, 0), Offset(80, 0)))
        assert picked is not None
        assert picked[0] == "please build the thing"
        assert "❯" not in picked[0]
    finally:
        await context.__aexit__(None, None, None)


async def test_a_heavy_chat_suggests_compacting(workdir):
    from eirene.core.session import Message

    provider = Script([TextDelta("ok"), Done("stop")],
                      [TextDelta("ok"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.config.set("context_warning", 100)
        app.session.messages = [Message.user("padding " * 200) for _ in range(5)]
        await type_line(pilot, "carry on")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        notices = [content(b) for b in blocks(app, NoticeBlock)]
        assert any("/compact" in text for text in notices)

        before = len(notices)
        await type_line(pilot, "again")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        again = [content(b) for b in blocks(app, NoticeBlock)]
        assert len([t for t in again if "/compact" in t]) == 1, "warn once only"
        assert len(again) >= before
    finally:
        await context.__aexit__(None, None, None)


async def test_a_light_chat_says_nothing_about_compacting(workdir):
    provider = Script([TextDelta("ok"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "short one")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert not any("/compact" in content(b) for b in blocks(app, NoticeBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_popup_opens_and_closes(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("the answer"), Done("stop")]))
    try:
        assert not app.aside.open
        await commands.dispatch(app, "/btw why is the sky blue")
        for _ in range(40):
            await pilot.pause()
            if "the answer" in app.aside.answer:
                break
        assert app.aside.open
        assert app.aside.question == "why is the sky blue"
        assert "the answer" in app.aside.answer

        await pilot.press("escape")
        await pilot.pause()
        assert not app.aside.open
        assert app.aside.answer == ""
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_popup_reports_a_failure(workdir):
    from eirene import commands
    from eirene.core.errors import ProviderError

    class Broken(Script):
        async def stream(self, *args, **kwargs):
            raise ProviderError("API key rejected")
            yield

    app, pilot, context = await start(workdir, Broken())
    try:
        await commands.dispatch(app, "/btw anything")
        for _ in range(40):
            await pilot.pause()
            if app.aside.failed:
                break
        assert app.aside.failed
        assert "rejected" in app.aside.answer
        assert app.is_running
    finally:
        await context.__aexit__(None, None, None)


async def test_btw_keeps_the_transcript_clean(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("side note"), Done("stop")]))
    try:
        before = len(app.transcript.children)
        await commands.dispatch(app, "/btw a question")
        for _ in range(40):
            await pilot.pause()
            if "side note" in app.aside.answer:
                break
        assert len(app.transcript.children) == before
        assert app.session.messages == []
    finally:
        await context.__aexit__(None, None, None)


async def test_an_answer_renders_markdown(workdir):
    provider = Script([TextDelta("Use **bold** and `code` here.\n"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "explain")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        shown = content(blocks(app, AnswerBlock)[0])
        assert shown == "Use bold and code here."
        assert "**" not in shown and "`" not in shown
    finally:
        await context.__aexit__(None, None, None)


async def test_markdown_in_an_answer_is_styled_on_screen(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("plain **bold** and `code` words")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()
        found = set()
        region = block.region
        for x in range(region.x, min(region.x + 40, app.size.width)):
            style = app.screen.get_style_at(x, region.y)
            found.add((style.bold, style.bgcolor.name if style.bgcolor else "-"))
        assert any(bold for bold, _ in found), "bold must reach the screen"
        assert any(bg != "-" and bg != "default" for _, bg in found), \
            "inline code needs its own background"
    finally:
        await context.__aexit__(None, None, None)


async def test_copying_an_answer_gives_the_rendered_text(workdir):
    from textual.geometry import Offset
    from textual.selection import Selection

    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("Run `pytest -q` and **rebuild**.")
        await app.push(block)
        block.flush()
        await pilot.pause()
        picked = block.get_selection(Selection(Offset(0, 0), Offset(80, 0)))
        assert picked is not None
        assert picked[0] == "Run pytest -q and rebuild."
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_popup_renders_markdown(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("It lives in `main.py`, **not** here."), Done("stop")]))
    try:
        await commands.dispatch(app, "/btw where is it")
        for _ in range(40):
            await pilot.pause()
            if "main.py" in app.aside.answer:
                break
        rendered = content(app.aside.body)
        assert "`" not in rendered
        assert "main.py" in rendered
    finally:
        await context.__aexit__(None, None, None)


async def push_blocks(app, workdir):
    """A user line, an answer and a change card."""
    from eirene.tools import files
    from eirene.tools.sandbox import Sandbox
    from eirene.ui.chat import ChangeBlock

    (workdir / "code.py").write_text("def go():\n    return 1\n", encoding="utf-8")
    text = files.diff_preview(Sandbox(workdir), "code.py",
                              "def go():\n    return 2\n")
    user = await app.push(UserBlock("please explain the parser"))
    answer = AnswerBlock()
    answer.feed("The **parser** reads `tokens.py` slowly.")
    await app.push(answer)
    answer.flush()
    change = await app.push(ChangeBlock("code.py", text, "Update"))
    return user, answer, change


async def test_every_block_maps_the_mouse_to_a_character(workdir):
    app, pilot, context = await start(workdir)
    try:
        blocks_shown = await push_blocks(app, workdir)
        await pilot.pause()
        await pilot.pause()
        for block in blocks_shown:
            _, offset = app.screen.get_widget_and_offset_at(4, block.region.y)
            assert offset is not None, (
                f"{type(block).__name__} must map to a character offset, "
                "or the mouse selects the whole widget")
    finally:
        await context.__aexit__(None, None, None)


async def test_dragging_selects_only_what_was_dragged(workdir):
    app, pilot, context = await start(workdir)
    try:
        user, answer, change = await push_blocks(app, workdir)
        await pilot.pause()
        await pilot.pause()

        app.screen.clear_selection()
        await pilot.mouse_down(offset=(4, answer.region.y))
        await pilot.hover(offset=(23, answer.region.y))
        await pilot.mouse_up(offset=(23, answer.region.y))
        await pilot.pause()
        picked = app.screen.get_selected_text()
        assert picked.strip() == "parser reads tokens."
        assert "**" not in picked and "`" not in picked
        assert "\n" not in picked, "one dragged row, one line of text"
    finally:
        await context.__aexit__(None, None, None)


async def test_dragging_a_change_card_gives_bare_code(workdir):
    app, pilot, context = await start(workdir)
    try:
        _, _, change = await push_blocks(app, workdir)
        await pilot.pause()
        await pilot.pause()
        app.screen.clear_selection()
        row = change.region.y + 3
        await pilot.mouse_down(offset=(8, row))
        await pilot.hover(offset=(40, row))
        await pilot.mouse_up(offset=(40, row))
        await pilot.pause()
        picked = app.screen.get_selected_text()
        assert "return 1" in picked
        assert not picked.lstrip().startswith(("+", "-"))
        assert "1 " not in picked[:4]
    finally:
        await context.__aexit__(None, None, None)


async def test_dragging_a_user_line_drops_the_marker(workdir):
    app, pilot, context = await start(workdir)
    try:
        user, _, _ = await push_blocks(app, workdir)
        await pilot.pause()
        await pilot.pause()
        app.screen.clear_selection()
        await pilot.mouse_down(offset=(0, user.region.y))
        await pilot.hover(offset=(30, user.region.y))
        await pilot.mouse_up(offset=(30, user.region.y))
        await pilot.pause()
        picked = app.screen.get_selected_text()
        assert "❯" not in picked
        assert "please explain the parser" in picked
    finally:
        await context.__aexit__(None, None, None)


async def test_a_table_in_an_answer_is_drawn_and_selectable(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("| File | Lines |\n|------|------:|\n| `a.py` | 12 |\n")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()

        shown = content(block)
        assert "┌" in shown and "│" in shown and "└" in shown
        assert "|---" not in shown and "`" not in shown

        row = block.region.y + 3
        _, offset = app.screen.get_widget_and_offset_at(4, row)
        assert offset is not None, "a table must still map the mouse"
        app.screen.clear_selection()
        await pilot.mouse_down(offset=(2, row))
        await pilot.hover(offset=(12, row))
        await pilot.mouse_up(offset=(12, row))
        await pilot.pause()
        assert "a.py" in app.screen.get_selected_text()
    finally:
        await context.__aexit__(None, None, None)


async def test_every_markdown_style_reaches_the_screen(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("**BB** *II* <u>UU</u> ~~SS~~ `CC` plain")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()

        shown = content(block)
        assert shown == "BB II UU SS CC plain"
        found = {"bold": False, "italic": False, "underline": False,
                 "strike": False, "code": False}
        region = block.region
        for x in range(region.x, min(region.x + 30, app.size.width)):
            style = app.screen.get_style_at(x, region.y)
            found["bold"] |= bool(style.bold)
            found["italic"] |= bool(style.italic)
            found["underline"] |= bool(style.underline)
            found["strike"] |= bool(style.strike)
            if style.bgcolor and style.bgcolor.name not in ("default",):
                found["code"] = True
        missing = [name for name, seen in found.items() if not seen]
        assert not missing, f"these never reached the screen: {missing}"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_popup_answer_is_selectable(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("It lives in `main.py` and is **small**."), Done("stop")]))
    try:
        await commands.dispatch(app, "/btw where is it")
        for _ in range(40):
            await pilot.pause()
            if "main.py" in app.aside.answer:
                break
        await pilot.pause()
        body = app.aside.body
        _, offset = app.screen.get_widget_and_offset_at(
            body.region.x + 2, body.region.y + 1)
        assert offset is not None, "the popup answer must map the mouse"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_code_block_in_an_answer_is_a_panel(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("Here you go:\n\n```python\nnums = [1, 2, 3]\n"
                   "print(nums)  # ok\n```\n\nDone.")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()

        shown = content(block)
        assert "```" not in shown, "the backticks must not be on screen"
        assert "nums = [1, 2, 3]" in shown

        backgrounds, colours = 0, set()
        region = block.region
        for y in range(region.y, min(region.y + region.height, app.size.height)):
            row = set()
            for x in range(region.x, min(region.x + 30, app.size.width)):
                style = app.screen.get_style_at(x, y)
                if style.bgcolor and style.bgcolor.name == "#282a36":
                    row.add("background")
                if style.color:
                    colours.add(style.color.name)
            if row:
                backgrounds += 1
        assert backgrounds == 0, "fenced chat code should have no background"
        assert "╭─ python" in shown and "╰" in shown
        assert len(colours) > 3, f"code needs real highlighting, saw {colours}"
    finally:
        await context.__aexit__(None, None, None)


async def test_copying_code_from_an_answer_is_verbatim(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("```python\nnums = [1, 2, 3, 4, 5]\nprint(nums)\n```")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()

        row = block.region.y + 1
        app.screen.clear_selection()
        await pilot.mouse_down(offset=(0, row))
        await pilot.hover(offset=(60, row))
        await pilot.mouse_up(offset=(60, row))
        await pilot.pause()
        picked = app.screen.get_selected_text()
        assert picked == "nums = [1, 2, 3, 4, 5]", repr(picked)
    finally:
        await context.__aexit__(None, None, None)


async def test_inline_code_is_white_on_grey(workdir):
    app, pilot, context = await start(workdir)
    try:
        block = AnswerBlock()
        block.feed("run `pytest` now")
        await app.push(block)
        block.flush()
        await pilot.pause()
        await pilot.pause()
        seen = []
        region = block.region
        for x in range(region.x, min(region.x + 20, app.size.width)):
            style = app.screen.get_style_at(x, region.y)
            if style.bgcolor and style.bgcolor.name not in ("default",):
                seen.append((style.color.name if style.color else "-",
                             style.bgcolor.name))
        assert seen, "inline code needs a background"
        colour, background = seen[0]
        assert background == "#3b4149", f"grey background, got {background}"
        assert colour == "#f0f6fc", f"white text, got {colour}"
    finally:
        await context.__aexit__(None, None, None)


async def test_sent_user_messages_use_the_darker_grey_background(workdir):
    app, pilot, context = await start(workdir)
    try:
        message = await app.push(UserBlock("already sent"))
        await pilot.pause()
        style = app.screen.get_style_at(message.region.x + 2, message.region.y)
        assert style.bgcolor and style.bgcolor.name == "#30343a"
        assert style.color and style.color.name == "#f8f8f2"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_picker_shows_the_highlighted_description(workdir):
    app, pilot, context = await start(workdir)
    try:
        picker = app.picker
        asking = asyncio.create_task(picker.choose("pick one", [
            ("a", "alpha", "on", "The first skill, for doing alpha things."),
            ("b", "beta", "off", "The second skill, for beta work."),
        ]))
        await pilot.pause()
        shown = " ".join(content(picker).split())
        assert "The first skill, for doing alpha things." in shown
        assert "The second skill, for beta work." not in shown

        await pilot.press("down")
        await pilot.pause()
        shown = " ".join(content(picker).split())
        assert "The second skill, for beta work." in shown
        assert "The first skill, for doing alpha things." not in shown

        await pilot.press("escape")
        assert await asking is None
    finally:
        await context.__aexit__(None, None, None)


async def test_picker_highlight_fills_the_whole_row(workdir):
    app, pilot, context = await start(workdir, size=(100, 32))
    try:
        asking = asyncio.create_task(app.picker.choose("choose a model", [
            ("a", "model-a", "fast"), ("b", "model-b", "capable"),
        ]))
        await pilot.pause()
        await pilot.pause()
        body = app.picker._Static__content
        spans = [span for span in body.spans if "reverse" in str(span.style)]
        assert spans
        selected = body.plain[spans[0].start:spans[0].end]
        assert "model-a" in selected and "fast" in selected
        assert len(selected) >= app.picker.size.width - 4
        await pilot.press("escape")
        assert await asking is None
    finally:
        await context.__aexit__(None, None, None)


async def test_permission_highlight_fills_the_whole_row(workdir):
    app, pilot, context = await start(workdir, size=(100, 32))
    try:
        asking = asyncio.create_task(app.permission.ask("run tests", "requested"))
        await pilot.pause()
        await pilot.pause()
        body = app.permission._Static__content
        spans = [span for span in body.spans if "reverse" in str(span.style)]
        assert spans
        selected = body.plain[spans[0].start:spans[0].end]
        assert "1. yes" in selected
        assert len(selected) >= app.permission.size.width - 4
        await pilot.press("n")
        assert await asking == "no"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_picker_without_descriptions_still_works(workdir):
    app, pilot, context = await start(workdir)
    try:
        picker = app.picker
        asking = asyncio.create_task(picker.choose("pick", [
            ("a", "alpha", "hint"), ("b", "beta", ""),
        ]))
        await pilot.pause()
        assert "alpha" in content(picker)
        await pilot.press("enter")
        assert await asking == "a"
    finally:
        await context.__aexit__(None, None, None)


async def test_skills_lists_the_shipped_examples(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir)
    try:
        listing = asyncio.create_task(commands.dispatch(app, "/skills"))
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting, "the skill list should open"
        shown = content(app.picker)
        assert "systemd" in shown.lower()
        assert "python" in shown.lower()
        assert "systemd" in shown.lower()
        await pilot.press("escape")
        await listing
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_window_floats_in_the_middle(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("a short answer"), Done("stop")]), size=(100, 40))
    try:
        await commands.dispatch(app, "/btw why")
        for _ in range(40):
            await pilot.pause()
            if "short answer" in app.aside.answer:
                break
        await pilot.pause()
        await pilot.pause()

        window = app.aside.region
        assert app.aside.open
        assert window.width < app.size.width, "it is a window, not a bar"
        assert window.height < app.size.height, "it must not cover the screen"
        left, right = window.x, app.size.width - window.right
        assert abs(left - right) <= 1, f"not centred: {left} vs {right}"
        above, below = window.y, app.size.height - window.bottom
        assert above > 0 and below > 0, "it should float, not touch the edges"
        assert abs(above - below) <= 2, f"not middled: {above} vs {below}"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_chat_stays_visible_around_the_btw_window(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("the answer"), Done("stop")]), size=(100, 40))
    try:
        for index in range(24):
            await app.push(NoticeBlock(f"chat line {index}"))
        await pilot.pause()
        await commands.dispatch(app, "/btw why")
        for _ in range(40):
            await pilot.pause()
            if "the answer" in app.aside.answer:
                break
        await pilot.pause()

        window = app.aside.region
        above = app.screen.get_style_at(2, max(window.y - 2, 0))
        beside = app.screen.get_style_at(1, window.y + 1)
        assert (above.bgcolor is None or above.bgcolor.name != "#282a36"), \
            "the chat above the window must still be drawn"
        assert (beside.bgcolor is None or beside.bgcolor.name != "#282a36"), \
            "the window must not blank the whole row"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_window_hides_the_chat_behind_it(workdir):
    from eirene import commands
    from eirene.ui.aside import POPUP_BACKGROUND

    app, pilot, context = await start(workdir, Script(
        [TextDelta("the answer"), Done("stop")]), size=(100, 40))
    try:
        for index in range(30):
            await app.push(NoticeBlock(f"chat line {index}"))
        await pilot.pause()

        await commands.dispatch(app, "/btw why")
        for _ in range(40):
            await pilot.pause()
            if "the answer" in app.aside.answer:
                break
        await pilot.pause()

        window = app.aside.region
        middle = window.y + 1
        inside = app.screen.get_style_at(window.x + 2, middle)
        assert inside.bgcolor is not None
        assert inside.bgcolor.name == POPUP_BACKGROUND, "the window must be opaque"
    finally:
        await context.__aexit__(None, None, None)


async def test_clicking_the_title_row_closes_the_btw_window(workdir):
    from eirene import commands

    app, pilot, context = await start(workdir, Script(
        [TextDelta("answered"), Done("stop")]), size=(100, 40))
    try:
        await commands.dispatch(app, "/btw why")
        for _ in range(40):
            await pilot.pause()
            if "answered" in app.aside.answer:
                break
        assert app.aside.open
        await pilot.pause()
        window = app.aside.region
        await pilot.click(offset=(window.x + 2, window.y + 1))
        await pilot.pause()
        assert not app.aside.open
    finally:
        await context.__aexit__(None, None, None)


async def test_a_question_from_the_model_becomes_a_picker(workdir):
    from eirene.tools.registry import CHAT_OPTION

    provider = Script(
        [ToolCall("c1", "ask_user",
                  {"question": "which database?",
                   "options": ["sqlite", "postgres"]}), Done("tool_use")],
        [TextDelta("using sqlite then"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.MANUAL
        await type_line(pilot, "set up storage")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting, "the question should become a choice"
        shown = content(app.picker)
        assert "which database?" in shown
        assert "sqlite" in shown and "postgres" in shown
        assert "chat about this" in shown, "there must be a way out"
        assert app.picker.options[-1][0] == CHAT_OPTION

        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert "using sqlite then" in content(blocks(app, AnswerBlock)[-1])
    finally:
        await context.__aexit__(None, None, None)


async def test_chatting_about_a_question_hands_back_the_input(workdir):
    provider = Script(
        [ToolCall("c1", "ask_user",
                  {"question": "which one?", "options": ["a", "b"]}),
         Done("tool_use")],
        [TextDelta("should not appear"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.mode = Mode.MANUAL
        await type_line(pilot, "go")
        for _ in range(40):
            await pilot.pause()
            if app.picker.waiting:
                break
        for _ in range(len(app.picker.options) - 1):
            await pilot.press("down")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        notices = [content(b) for b in blocks(app, NoticeBlock)]
        assert any("say what you think" in text for text in notices)
        assert not any("should not appear" in content(b)
                       for b in blocks(app, AnswerBlock))
        assert app.prompt.has_focus
    finally:
        await context.__aexit__(None, None, None)


async def test_the_slash_menu_highlights_the_whole_row(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.press("/", "c")
        await pilot.pause()
        body = app.slash._Static__content
        picked = [body.plain[s.start:s.end] for s in body.spans
                  if "reverse" in str(s.style)]
        assert picked, "the highlighted row needs a background"
        assert "/clear" in picked[0]
        assert "wipe the session" in picked[0], "the description must be covered too"
    finally:
        await context.__aexit__(None, None, None)


async def test_initial_slash_highlight_uses_laid_out_width(workdir):
    app, pilot, context = await start(workdir, size=(100, 35))
    try:
        await pilot.press("/")
        await pilot.pause()
        await pilot.pause()
        body = app.slash._Static__content
        spans = [span for span in body.spans if "reverse" in str(span.style)]
        assert spans
        highlighted = body.plain[spans[0].start:spans[0].end]
        assert len(highlighted) >= app.slash.size.width - 4
    finally:
        await context.__aexit__(None, None, None)


async def test_the_close_button_stays_in_the_corner(workdir):
    from eirene.ui.aside import CLOSE

    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        seen = []
        long_question = ("what is the best way to lay out a large python project "
                         "with many packages and a suite that runs quickly")
        for question, answer in ((long_question, "A long answer.\n" * 6),
                                 ("2+2", "4")):
            app.aside.ask(question)
            app.aside.feed(answer)
            app.aside.finish()
            await pilot.pause()
            await pilot.pause()
            panel = app.aside.region
            button = app.aside.close_button.region
            seen.append((button.y - panel.y, panel.right - button.right))
            assert app.aside.region.height > 0
            app.aside.close()
            await pilot.pause()

        assert len(set(seen)) == 1, f"the button moved: {seen}"
        top, right = seen[0]
        assert top == 1, "it must sit on the top row, inside the border"
        assert right <= 2, "it must sit against the right edge"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_close_button_reads_as_a_button(workdir):
    from eirene.ui.aside import CLOSE

    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        assert CLOSE == "[x]"
        app.aside.ask("anything")
        await pilot.pause()
        assert content(app.aside.close_button) == "[x]"
        assert "[x]" not in content(app.aside.body), "only one close button"
        assert "esc to close" not in content(app.aside.body)
    finally:
        await context.__aexit__(None, None, None)


async def test_clicking_the_close_button_closes_the_window(workdir):
    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        app.aside.ask("anything")
        app.aside.finish("an answer")
        await pilot.pause()
        await pilot.pause()
        assert app.aside.open
        button = app.aside.close_button.region
        await pilot.click(offset=(button.x + 1, button.y))
        await pilot.pause()
        assert not app.aside.open
    finally:
        await context.__aexit__(None, None, None)


async def test_the_question_never_pushes_the_button_down(workdir):
    app, pilot, context = await start(workdir, size=(80, 30))
    try:
        app.aside.ask("q " * 200)
        app.aside.finish("short")
        await pilot.pause()
        await pilot.pause()
        header = content(app.aside.body).splitlines()[0]
        assert "\n" not in header
        button = app.aside.close_button.region
        assert button.y - app.aside.region.y == 1
    finally:
        await context.__aexit__(None, None, None)


async def test_the_close_button_is_actually_drawn(workdir):
    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        app.aside.ask("what is 2+2")
        app.aside.finish("4")
        await pilot.pause()
        await pilot.pause()
        panel = app.aside.region
        strips = app.screen._compositor.render_strips()
        row = "".join(segment.text for segment in strips[panel.y + 1])
        assert "[x]" in row[panel.x:panel.right], f"not painted: {row!r}"
        assert row[panel.x:panel.right].rstrip().endswith("[x] │")
    finally:
        await context.__aexit__(None, None, None)


async def test_clicking_the_banner_animates_only_the_art(workdir):
    app, pilot, context = await start(workdir)
    try:
        await pilot.pause()
        banner = blocks(app, ArtBlock)[0]
        before = content(banner)
        picture = banner._picture_height()
        await pilot.click(banner, offset=(2, 0))
        await pilot.pause()
        assert banner._timer is not None
        banner._advance()
        body = banner._Static__content
        rows = body.plain.splitlines()
        cut = len("\n".join(rows[:picture]))
        assert all(span.start < cut for span in body.spans
                   if "bold" in str(span.style))
        banner._tick = 10
        banner.shimmer()
        assert banner._tick == 0, "another click should restart the animation"
        banner._stop()
        assert content(banner) == before
    finally:
        await context.__aexit__(None, None, None)


def test_every_banner_animation_draws_a_visible_effect():
    from eirene.ui import art

    seen = set()
    for picture in art.BANNERS:
        banner = ArtBlock(picture.strip("\n"))
        seen.add(banner._animation)
        banner._tick = 12
        body = banner._draw()
        assert body.spans, f"{banner._animation} must style part of the banner"
    assert seen == set(art.ANIMATIONS)


def test_scrambled_glyphs_travel_and_land_back_on_the_banner():
    from eirene.ui import art

    picture = art.BANNERS[2].strip("\n")
    rows = picture.splitlines()
    span = ArtBlock.EFFECT_TICKS["scramble"]
    inventory = sorted(glyph for glyph in "".join(rows) if glyph != " ")
    moved = False
    for tick in range(span):
        frame = art.scramble_frame(rows, tick, span)
        assert sorted(g for g in "".join(frame) if g != " ") == inventory, \
            "no glyph may be lost while they move"
        moved = moved or frame != rows
    assert moved, "the glyphs have to actually move"
    assert art.scramble_frame(rows, span, span) == rows, "and end up as Eirene"


def _drops(rows, tick):
    from eirene.ui import art

    frame = art.drip_frame(rows, tick)
    return [(row, column) for row, line in enumerate(frame)
            for column, glyph in enumerate(line)
            if column >= len(rows[row]) or rows[row][column] != glyph]


def test_the_bloody_banner_lets_a_drop_or_two_fall():
    from eirene.ui import art

    rows = art.BANNERS[art.DRIP_BANNER].strip("\n").splitlines()
    counts = {len(_drops(rows, tick)) for tick in range(art.DROP_CYCLE * 3)}
    assert counts and max(counts) <= art.DROPS_IN_FLIGHT, \
        "a couple of drops, not a flood"
    assert max(counts) > 0, "something has to fall"
    fell = False
    for tick in range(art.DROP_CYCLE * 3 - 1):
        here, later = _drops(rows, tick), _drops(rows, tick + 1)
        if here and later and min(r for r, _ in later) > min(r for r, _ in here):
            fell = True
    assert fell, "drops must move downward"
    for tick in range(art.DROP_CYCLE * 3):
        for row, column in _drops(rows, tick):
            assert column >= len(rows[row]) or rows[row][column] == " ", \
                "a drop must never land on a letter"


def test_the_dotted_glyphs_swell_and_shrink_like_stars():
    from eirene.ui import art

    rows = art.BANNERS[art.STAR_BANNER].strip("\n").splitlines()
    sizes, glows = set(), set()
    for tick in range(art.STAR_BANNER + 40):
        frame, glowing = art.star_frame(rows, tick)
        glows.add(frozenset(glowing))
        for row, line in enumerate(frame):
            for column, glyph in enumerate(line):
                if glyph != rows[row][column]:
                    assert rows[row][column] in art.STAR_GLYPHS, \
                        "only the dots may change"
                    assert glyph in art.STAR_SIZES
                    sizes.add(glyph)
    assert {"·", "•", "●"} <= sizes, "a star has to grow and shrink again"
    assert len(glows) > 1, "the glow has to move between stars"


def test_stars_never_disturb_the_solid_glyphs():
    from eirene.ui import art
    from rich.cells import cell_len

    rows = art.BANNERS[art.STAR_BANNER].strip("\n").splitlines()
    for tick in range(30):
        frame, _ = art.star_frame(rows, tick)
        assert [len(line) for line in frame] == [len(line) for line in rows]
        assert all(cell_len(line) == len(line) for line in frame)


@pytest.mark.parametrize("size", [(60, 24), (40, 16), (24, 10), (16, 8)])
async def test_a_smaller_terminal_keeps_everything_inside(workdir, size):
    from rich.cells import cell_len

    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        block = AnswerBlock()
        block.feed("Prose.\n\n```python\nnums = [1, 2, 3]\n```\n")
        await app.push(block)
        block.flush()
        app.aside.ask("a question long enough to need wrapping somewhere")
        app.aside.finish("An answer that also runs on for a little while.")
        await pilot.pause()

        await pilot.resize_terminal(*size)
        await pilot.pause()
        await pilot.pause()

        strips = app.screen._compositor.render_strips()
        widest = max(sum(cell_len(seg.text) for seg in strip) for strip in strips)
        assert widest <= size[0], f"a row overflowed: {widest} > {size[0]}"

        window = app.aside.region
        assert window.right <= size[0], "the window hangs off the right"
        assert window.bottom <= size[1], "the window hangs off the bottom"
        assert window.x >= 0 and window.y >= 0
    finally:
        await context.__aexit__(None, None, None)


async def test_growing_the_terminal_again_re_centres_the_window(workdir):
    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        app.aside.ask("question")
        app.aside.finish("answer")
        await pilot.pause()
        await pilot.resize_terminal(30, 12)
        await pilot.pause()
        await pilot.pause()
        small = app.aside.region.width

        await pilot.resize_terminal(100, 40)
        await pilot.pause()
        await pilot.pause()
        big = app.aside.region
        assert big.width > small, "it should grow back"
        left, right = big.x, 100 - big.right
        assert abs(left - right) <= 1, f"not re-centred: {left} vs {right}"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_btw_window_is_white_on_a_grey_question(workdir):
    from eirene.ui.aside import QUESTION, TEXT

    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        app.aside.ask("what is a file descriptor")
        app.aside.finish("A small integer the kernel hands you.")
        await pilot.pause()
        await pilot.pause()

        panel = app.aside.region
        header, body = {}, {}
        for x in range(panel.x + 1, panel.right - 1):
            style = app.screen.get_style_at(x, panel.y + 1)
            if style.color:
                header[style.color.name] = header.get(style.color.name, 0) + 1
            style = app.screen.get_style_at(x, panel.y + 2)
            if style.color:
                body[style.color.name] = body.get(style.color.name, 0) + 1

        assert QUESTION in header, f"the question should be grey, saw {header}"
        assert TEXT in header, "the label should be white"
        assert body and max(body, key=body.get) == TEXT, \
            f"the answer should be white, saw {body}"
    finally:
        await context.__aexit__(None, None, None)


async def test_code_in_the_btw_window_keeps_its_colours(workdir):
    from eirene.ui.aside import TEXT

    app, pilot, context = await start(workdir, size=(100, 40))
    try:
        app.aside.ask("show me")
        app.aside.finish("Like this:\n\n```python\nreturn None\n```\n")
        await pilot.pause()
        await pilot.pause()

        panel = app.aside.region
        found = set()
        for dy in range(1, panel.height - 1):
            for x in range(panel.x + 1, panel.right - 1):
                style = app.screen.get_style_at(x, panel.y + dy)
                if style.color:
                    found.add(style.color.name)
        from eirene.ui import palette

        assert TEXT in found, "prose stays white"
        assert palette.BLUE in found, "keywords keep the palette"
    finally:
        await context.__aexit__(None, None, None)


class Asker(Script):
    """Answers, then records what it was asked next."""

    def __init__(self, *turns, options=""):
        super().__init__(*turns)
        self.options = options
        self.option_calls = 0
        self.follow_up = []

    async def stream(self, messages, model, *, system="", **kwargs):
        from eirene.core.prompt import OPTIONS_PROMPT
        if system == OPTIONS_PROMPT:
            self.option_calls += 1
            yield TextDelta(self.options)
            yield Done("stop")
            return
        if self.calls:
            self.follow_up.append(str(messages[-1].get("content", "")))
        async for event in super().stream(messages, model, system=system, **kwargs):
            yield event


async def settle(app, pilot, tries=60):
    for _ in range(tries):
        await pilot.pause()
        if app.turn and app.turn.done() and not app.asides:
            return


async def test_a_prose_question_with_a_list_becomes_a_picker(workdir):
    provider = Asker(
        [TextDelta("Which layout do you want?\n\n- flat files\n- a src package"),
         Done("stop")],
        [TextDelta("using a src package"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "start a project")
        for _ in range(60):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting, "the question should become a choice"
        shown = content(app.picker)
        assert "Which layout do you want?" in shown
        assert "flat files" in shown and "a src package" in shown
        assert "chat about this" in shown
        assert provider.option_calls == 0, "the list was already there"

        await pilot.press("down", "enter")
        await settle(app, pilot)
        assert provider.follow_up[-1] == "a src package"
        assert any("a src package" in content(b) for b in blocks(app, UserBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_a_question_without_options_gets_them_from_the_model(workdir):
    provider = Asker(
        [TextDelta("Before I write anything, confirm what you want:"), Done("stop")],
        [TextDelta("building it now"), Done("stop")],
        options="go ahead as described\nkeep it minimal\nlet me adjust first")
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "write me a file manager")
        for _ in range(60):
            await pilot.pause()
            if app.picker.waiting:
                break
        assert app.picker.waiting, "a bare question must still offer choices"
        assert provider.option_calls == 1
        shown = content(app.picker)
        assert "go ahead as described" in shown
        assert "keep it minimal" in shown
        assert "chat about this" in shown

        await pilot.press("enter")
        await settle(app, pilot)
        assert provider.follow_up[-1] == "go ahead as described"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_finished_answer_offers_nothing(workdir):
    provider = Asker([TextDelta("Done. I wrote three files."), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "do it")
        await settle(app, pilot)
        assert not app.picker.waiting
        assert provider.option_calls == 0
    finally:
        await context.__aexit__(None, None, None)


async def test_chatting_instead_of_choosing_leaves_the_input_free(workdir):
    provider = Asker(
        [TextDelta("Which one?\n\n- a\n- b"), Done("stop")],
        [TextDelta("should not run"), Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "go")
        for _ in range(60):
            await pilot.pause()
            if app.picker.waiting:
                break
        for _ in range(len(app.picker.options) - 1):
            await pilot.press("down")
        await pilot.press("enter")
        await settle(app, pilot)
        assert not any("should not run" in content(b)
                       for b in blocks(app, AnswerBlock))
        assert app.prompt.has_focus
    finally:
        await context.__aexit__(None, None, None)


async def test_a_useless_option_list_is_dropped(workdir):
    provider = Asker(
        [TextDelta("Shall I start?"), Done("stop")],
        [TextDelta("later"), Done("stop")],
        options="only one line")
    app, pilot, context = await start(workdir, provider)
    try:
        await type_line(pilot, "go")
        await settle(app, pilot)
        assert not app.picker.waiting, "one option is not a choice"
    finally:
        await context.__aexit__(None, None, None)


def _sent_colour(block):
    content = block._Static__content
    spans = [str(span.style) for span in content.spans]
    return spans[-1] if spans else str(content.style)


async def test_gruvbox_paints_each_section_its_own_colour(workdir):
    from eirene.ui import markup, theme
    from eirene.ui.chat import ThinkingBlock, ToolBlock
    from eirene.ui.composer import Marker, Rule

    app, pilot, context = await start(workdir)
    try:
        app.theme = theme.THEMES["gruvbox"].name
        await pilot.pause()
        sent = await app.push(UserBlock("hello"))
        think = await app.push(ThinkingBlock())
        tool = await app.push(ToolBlock("Read", "calc.py"))
        await pilot.pause()

        assert _sent_colour(sent) == "#fe8019", "the user speaks in gruvbox orange"
        assert str(app.query_one(Marker)._Static__content.style) == "bold #fe8019"
        assert str(app.query_one(Rule)._Static__content.style) == "#98971a"
        assert "italic #928374" == str(think._Static__content.style)
        label = [str(span.style) for span in tool._Static__content.spans][-1]
        assert label == "bold #8ec07c", "tools get their own colour"
        assert markup.STYLES["code"] == "#b8bb26 on #3c3836"
    finally:
        await context.__aexit__(None, None, None)


async def test_leaving_gruvbox_puts_every_colour_back(workdir):
    from eirene.ui import markup, theme
    from eirene.ui.chat import ThinkingBlock
    from eirene.ui.composer import Marker, Rule

    app, pilot, context = await start(workdir)
    try:
        sent = await app.push(UserBlock("hello"))
        think = await app.push(ThinkingBlock())
        await pilot.pause()
        plain = (_sent_colour(sent), str(think._Static__content.style),
                 str(app.query_one(Rule)._Static__content.style),
                 str(app.query_one(Marker)._Static__content.style),
                 markup.STYLES["code"])

        app.theme = theme.THEMES["gruvbox"].name
        await pilot.pause()
        assert _sent_colour(sent) == "#fe8019"

        app.theme = theme.THEMES["matrix"].name
        await pilot.pause()
        assert (_sent_colour(sent), str(think._Static__content.style),
                str(app.query_one(Rule)._Static__content.style),
                str(app.query_one(Marker)._Static__content.style),
                markup.STYLES["code"]) == plain, \
            "a theme without accents must look exactly as it did before"
    finally:
        await context.__aexit__(None, None, None)


def test_the_accented_themes_each_have_three_voices():
    from eirene.ui import theme

    plain = {key for key in theme.THEMES
             if theme.accents(theme.THEMES[key].name) is None}
    assert plain == {"default", "matrix", "hacker-red"}, \
        "the single-colour themes stay single-colour"
    themed = set(theme.THEMES) - plain
    assert theme.accents(theme.THEMES["gruvbox"].name).art == "#fe8019"
    for key in themed:
        accent = theme.accents(theme.THEMES[key].name)
        assert accent.marker == accent.sent == accent.art, \
            f"{key} must speak with one headline colour"
        voices = {accent.art, accent.detail, accent.rule}
        assert len(voices) == 3, f"{key} needs a headline, a body and a frame"
        assert len({accent.tool, accent.thinking, accent.glow, accent.spark}) == 4, \
            f"{key} must not collapse its sections into one colour"
        assert accent.code and " on " in accent.code, key


def _colours(block):
    """Map each styled run of the block to its colour."""
    content = block._Static__content
    return {content.plain[span.start:span.end]: str(span.style)
            for span in content.spans}


async def test_the_intro_panel_speaks_in_two_colours(workdir):
    from eirene.ui import theme
    from eirene.ui.chat import ArtBlock

    app, pilot, context = await start(workdir)
    try:
        app.theme = theme.THEMES["gruvbox"].name
        await pilot.pause()
        banner = blocks(app, ArtBlock)[0]
        painted = _colours(banner)
        picture = banner._picture_height()
        drawing = banner._lines()[0]

        assert painted.get(drawing) == "#fe8019", "the drawing is the headline colour"
        assert painted.get("Tip:") == "bold #bdae93", "the label is the quiet one"
        for glyph in ("▰", "↗", "ⓘ"):
            assert painted.get(glyph) == "#fe8019", glyph
        assert "─" in painted and painted["─"] == "#98971a", "the frame stays green"
        rows = banner._lines()[picture:]
        detail = [line for line in rows if "session" in line]
        assert detail and painted.get(detail[0]) == "#bdae93", "detail is quiet cream"
        tip = [line for line in rows if "Tip:" in line][0]
        after = tip[tip.index("│") + 1:]
        assert painted.get(after) == "#fe8019", "the tip itself carries the orange"
    finally:
        await context.__aexit__(None, None, None)


async def test_the_banner_repaints_when_the_theme_changes(workdir):
    from eirene.ui import theme
    from eirene.ui.chat import ArtBlock

    app, pilot, context = await start(workdir)
    try:
        banner = blocks(app, ArtBlock)[0]
        app.theme = theme.THEMES["gruvbox"].name
        await pilot.pause()
        assert any(style == "#fe8019" for style in _colours(banner).values())

        app.theme = theme.THEMES["matrix"].name
        await pilot.pause()
        styles = set(_colours(banner).values())
        assert not any("#fe8019" in style for style in styles), \
            "a theme without accents must not keep the last theme's colours"
        assert styles == {"dim"}, "it falls back to the plain dim drawing"
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("key", ["gruvbox", "catppuccin", "tokyo-night",
                                 "dracula", "nord", "solarized-dark",
                                 "monokai", "one-dark", "rose-pine", "ayu-dark"])
async def test_banner_animations_follow_the_theme(workdir, key):
    from eirene.ui import art, theme
    from eirene.ui.chat import ArtBlock

    app, pilot, context = await start(workdir)
    try:
        app.theme = theme.THEMES[key].name
        await pilot.pause()
        accent = theme.accents(app.theme)
        banner = blocks(app, ArtBlock)[0]
        for name, index in (("scramble", 1), ("drip", art.DRIP_BANNER),
                            ("stars", art.STAR_BANNER)):
            banner.art = art.BANNERS[index].strip("\n")
            banner._animation = name
            banner._tick = 10
            styles = {str(span.style) for span in banner._draw().spans}
            assert styles, f"{key}/{name} draws nothing"
            assert not any("reverse" in style or "bright_" in style
                           for style in styles), \
                f"{key}/{name} still uses a hard-coded terminal colour"
            assert any(accent.glow in style or accent.spark in style
                       for style in styles), f"{key}/{name} ignores the theme"
    finally:
        await context.__aexit__(None, None, None)


def test_a_theme_without_accents_keeps_its_plain_animation():
    from eirene.ui import art
    from eirene.ui.chat import ArtBlock

    banner = ArtBlock(art.BANNERS[1].strip("\n"))
    banner._animation = "scramble"
    banner._tick = 10
    assert "bold reverse" in {str(span.style) for span in banner._draw().spans}


def test_every_accent_reads_against_its_own_background():
    from eirene.ui import theme

    def luminance(colour):
        channels = (int(colour[index:index + 2], 16) / 255 for index in (1, 3, 5))
        parts = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
                 for c in channels]
        return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]

    def contrast(one, two):
        high, low = sorted((luminance(one), luminance(two)), reverse=True)
        return (high + 0.05) / (low + 0.05)

    for key, built in theme.THEMES.items():
        accent = theme.accents(built.name)
        if accent is None:
            continue
        for field in ("art", "detail", "rule", "tool", "glow", "spark"):
            colour = getattr(accent, field)
            assert contrast(colour, built.background) >= 2.5, \
                f"{key}.{field} ({colour}) is too dark to read"
        assert contrast(accent.thinking, built.background) >= 2.0, \
            f"{key}.thinking is invisible, not merely quiet"


def test_every_theme_can_be_offered_by_the_picker():
    from eirene.commands.theme import DESCRIPTIONS
    from eirene.ui import theme

    assert set(DESCRIPTIONS) == set(theme.THEMES), \
        "/theme reads a description per theme and raises without one"
    assert set(theme.LABELS) == set(theme.THEMES)


def test_there_are_light_themes_and_they_are_marked_light():
    from eirene.ui import theme

    light = {key for key, built in theme.THEMES.items() if not built.dark}
    assert light == {"solarized-light", "gruvbox-light", "latte"}
    for key in light:
        built = theme.THEMES[key]
        assert theme.accents(built.name) is not None, f"{key} needs its accents"
        assert built.background.lower() > "#c", f"{key} must actually be light"


@pytest.mark.parametrize("key", ["solarized-light", "gruvbox-light", "latte"])
async def test_a_light_theme_never_shows_a_dark_slab(workdir, key):
    from eirene.ui import theme

    app, pilot, context = await start(workdir)
    try:
        app.theme = theme.THEMES[key].name
        await pilot.pause()
        row = await app.push(UserBlock("hello"))
        await pilot.pause()
        accent = theme.accents(app.theme)
        assert str(row.styles.background.hex).lower() == accent.surface.lower(), \
            "the sent row sits on the theme's own panel"
        assert accent.surface != "#30343a", "not the hard-coded dark grey"
    finally:
        await context.__aexit__(None, None, None)


async def test_a_theme_without_accents_keeps_the_plain_sent_row(workdir):
    app, pilot, context = await start(workdir)
    try:
        row = await app.push(UserBlock("hello"))
        await pilot.pause()
        assert row.styles.background.hex.lower() == "#30343a"
    finally:
        await context.__aexit__(None, None, None)


ESCAPES = "\x1b[2J\x1b[H wiped \x1b[3J\r over \x07 done\n"


async def test_a_command_that_paints_the_screen_cannot_wipe_the_interface(workdir):
    """A curses app or ASCII animation must not clear the terminal."""
    from eirene.ui.chat import (AnswerBlock, CommandBlock, DiffBlock,
                                NoticeBlock, ToolBlock)
    from eirene.ui.composer import Prompt

    app, pilot, context = await start(workdir)
    try:
        card = await app.push(ToolBlock("Bash", f"./donut{ESCAPES}"))
        card.feed(ESCAPES)
        card.finish(ESCAPES, False, 1.0)
        card.flush()
        ran = await app.push(CommandBlock("Bash", "./donut"))
        ran.feed(ESCAPES)
        ran.finish(ESCAPES, False, 1.0)
        ran.flush()
        answer = await app.push(AnswerBlock())
        answer.feed(f"here it is {ESCAPES}")
        answer.flush()
        await app.push(UserBlock(f"pasted {ESCAPES}"))
        await app.push(DiffBlock(f"write {ESCAPES}", f"--- a\n+++ b\n+{ESCAPES}"))
        await app.push(NoticeBlock(ESCAPES, "warn"))
        await pilot.pause()

        painted = "".join(strip.text for strip
                          in app.screen._compositor.render_strips())
        for hostile, what in (("\x1b", "an escape sequence"), ("\r", "a carriage return"),
                              ("\x07", "a bell")):
            assert hostile not in painted, f"{what} reached the terminal"
        assert app.query_one(Prompt).region.height > 0, "the input bar survives"
        assert "wiped" in painted and "done" in painted, "the text itself is kept"
    finally:
        await context.__aexit__(None, None, None)


async def test_no_side_panel_can_wipe_the_screen(workdir):
    """The /btw window and the status line show untrusted text too."""
    app, pilot, context = await start(workdir)
    try:
        app.aside.ask(f"question {ESCAPES}")
        app.aside.feed(f"streamed {ESCAPES}")
        app.aside.finish(f"answer {ESCAPES}")
        app.say(f"notice {ESCAPES}", "warn")
        app.status.start()
        app.status.set_phase(f"phase {ESCAPES}")
        await pilot.pause()
        await pilot.pause()
        painted = "".join(strip.text for strip
                          in app.screen._compositor.render_strips())
        for hostile, what in (("\x1b", "an escape"), ("\r", "a carriage return"),
                              ("\x07", "a bell")):
            assert hostile not in painted, f"{what} reached the terminal"
    finally:
        await context.__aexit__(None, None, None)


def test_escapes_are_stripped_without_losing_the_output():
    from eirene.ui.format import strip_escapes

    assert strip_escapes("\x1b[H\x1b[J  donut\r\n\x1b[2Kmade by eirene\x07\n") == \
        "  donut\nmade by eirene\n"
    assert strip_escapes("plain") == "plain"
    assert strip_escapes("") == ""
    assert strip_escapes("keeps\nits\nlines") == "keeps\nits\nlines"
    assert strip_escapes("\x1b[38;2;255;0;0mred\x1b[0m") == "red"
