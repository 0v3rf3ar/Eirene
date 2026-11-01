"""Connection health is shown by shade, and real activity restores it."""
from types import SimpleNamespace

import pytest

from eirene.ui import status as status_mod
from eirene.ui.status import StatusLine


@pytest.fixture
def clocked_status(monkeypatch):
    clock = SimpleNamespace(now=100.0)
    monkeypatch.setattr(status_mod, "time", SimpleNamespace(monotonic=lambda: clock.now))
    status = StatusLine()
    frames = []
    monkeypatch.setattr(status, "update", frames.append)
    status.start()
    return status, clock, frames


def test_silence_progressively_fades_and_activity_restores_brightness(clocked_status):
    status, clock, frames = clocked_status
    colours = []
    for seconds, expected in ((0, 0), (5, 1), (15, 2), (30, 3), (60, 4)):
        clock.now = 100 + seconds
        status._refresh()
        assert status.shade_level == expected
        colours.append(frames[-1].spans[0].style.color.get_truecolor().red)
    assert all(a > b for a, b in zip(colours, colours[1:]))
    status.mark_activity()
    assert status.shade_level == 0
    assert frames[-1].spans[0].style.bold


def test_retry_ticks_do_not_reset_fading_or_show_connection_text(clocked_status):
    status, clock, frames = clocked_status
    status.set_phase("reconnecting")
    assert status.shade_level == 1
    for seconds, expected in ((15, 2), (30, 3), (60, 4)):
        clock.now = 100 + seconds
        status.set_phase("waiting for response")
        assert status.shade_level == expected
        assert "reconnecting" not in frames[-1].plain
        assert "waiting for response" not in frames[-1].plain
    status.set_tokens(100, 1)
    assert status.shade_level == 4, "usage bookkeeping is not response activity"
    status.set_phase("answering")
    assert status.shade_level == 0


def test_tools_and_user_input_waits_do_not_look_disconnected(clocked_status):
    status, clock, _ = clocked_status
    status.start_tool("read")
    clock.now += 100
    assert status.shade_level == 0
    status.finish_tool("read")
    status.set_phase("waiting for input")
    clock.now += 100
    assert status.shade_level == 0


def test_new_turn_and_stop_clear_connection_state(clocked_status):
    status, clock, frames = clocked_status
    status.set_connection_wait()
    clock.now += 100
    assert status.shade_level == 4
    status.stop("timed out")
    assert not status.active
    assert "timed out" in frames[-1].plain
    status.start()
    assert status.shade_level == 0


async def test_retry_messages_stay_hidden_until_real_response_resumes(workdir):
    import asyncio
    from eirene.providers.base import ConnectionStatus, Done, TextDelta, Usage
    from test_tui import Script, start, type_line, content, blocks
    from eirene.ui.chat import NoticeBlock

    resume = asyncio.Event()
    finish = asyncio.Event()

    class Reconnecting(Script):
        async def stream(self, *args, **kwargs):
            yield ConnectionStatus("rate limited; retrying in 10s")
            yield Usage(10, 0)
            await resume.wait()
            yield TextDelta("Back online")
            await finish.wait()
            yield Done("stop")

    app, pilot, context = await start(workdir, Reconnecting())
    try:
        await type_line(pilot, "work")
        for _ in range(40):
            await pilot.pause()
            if app.status._connection_wait:
                break
        assert app.status._connection_wait
        app.status._last_activity -= 65
        app.status._refresh()
        assert app.status.shade_level == 4
        assert "rate limited" not in content(app.status)
        assert "retrying" not in content(app.status)
        assert all("rate limited" not in content(block) and "retrying" not in content(block)
                   for block in blocks(app, NoticeBlock))
        resume.set()
        for _ in range(40):
            await pilot.pause()
            if app.status.phase == "answering":
                break
        assert app.status.active and app.status.shade_level == 0
        assert not app.status._connection_wait
    finally:
        resume.set()
        finish.set()
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("theme_name", ["default", "matrix", "gruvbox-light"])
async def test_shades_follow_theme_and_reduced_motion(workdir, theme_name):
    from eirene.ui.theme import THEMES, _contrast
    from test_tui import start

    app, pilot, context = await start(workdir)
    try:
        app.theme = THEMES[theme_name].name
        app.config.set("reduce_motion", True)
        await pilot.pause()
        app.status.start()
        styles = [app.status._working_style(level) for level in range(5)]
        colours = [style.color.name for style in styles]
        assert len(set(colours)) == 5
        if theme_name != "default":
            contrasts = [_contrast(colour, THEMES[theme_name].background) for colour in colours]
            assert all(a > b for a, b in zip(contrasts, contrasts[1:]))
        app.status._last_activity -= 65
        app.status._refresh()
        body = app.status._Static__content
        assert "*" in body.plain
        assert body.spans[0].style == styles[-1]
    finally:
        await context.__aexit__(None, None, None)


def test_background_idle_has_no_spinner_and_resumes_on_thinking(clocked_status, monkeypatch):
    status, clock, frames = clocked_status
    status.set_phase("idle")
    with monkeypatch.context() as patch:
        patch.setattr(status_mod.art, "spinner_frame", lambda *args: pytest.fail("idle animated"))
        clock.now += 10
        status._refresh()
    assert status.active
    assert frames[-1].plain == "  • idle · waiting for background commands  esc to stop"
    status.set_phase("thinking")
    assert "waiting for background commands" not in frames[-1].plain


def test_working_line_shows_timer_and_activity(clocked_status):
    status, clock, frames = clocked_status
    dot = status_mod.art.icon("dot")
    status._refresh()
    assert frames[-1].plain.endswith(f"… (0s {dot} thinking)")
    clock.now = 100 + 63
    status.set_phase("reasoning")
    assert frames[-1].plain.endswith(f"… (1m 3s {dot} reasoning)")
    status.set_phase("answering")
    assert frames[-1].plain.endswith(f"{dot} answering)")
    status.start_tool("a", "read")
    assert frames[-1].plain.endswith(f"{dot} searching)")
    status.start_tool("b", "write")
    assert frames[-1].plain.endswith(f"{dot} coding)")
    status.finish_tool("b")
    status.finish_tool("a")
    status.set_phase("running")
    assert frames[-1].plain.endswith(f"{dot} coding)")
    status.set_phase("waiting for confirmation")
    assert frames[-1].plain.endswith(f"{dot} thinking)")


def test_elapsed_label():
    assert status_mod.elapsed_label(-1) == "0s"
    assert status_mod.elapsed_label(59.9) == "59s"
    assert status_mod.elapsed_label(63) == "1m 3s"
    assert status_mod.elapsed_label(3721) == "1h 2m 1s"
    assert status_mod.elapsed_label(3600) == "1h 0m 0s"
    assert status_mod.elapsed_label(90061) == "25h 1m 1s"


def test_clock_label_is_twelve_hour():
    from datetime import datetime
    assert status_mod.clock_label(datetime(2026, 11, 1, 19, 38)) == "7:38 PM"
    assert status_mod.clock_label(datetime(2026, 11, 1, 0, 5)) == "12:05 AM"
    assert status_mod.clock_label(datetime(2026, 11, 1, 12, 0)) == "12:00 PM"
    assert status_mod.clock_label(datetime(2026, 11, 1, 9, 7)) == "9:07 AM"


async def test_turn_note_ends_with_finish_time(workdir):
    from datetime import datetime
    from eirene.core.agent import TurnDone
    from eirene.core.usage import Usage
    from test_tui import start
    app, pilot, context = await start(workdir)
    try:
        at = datetime(2026, 11, 1, 19, 38)
        dot = status_mod.art.icon("tokens")
        done = TurnDone(3.2, 0.5, Usage(output_tokens=190))
        note = app._turn_note(done, at)
        verb, rest = note.split(" for ", 1)
        assert verb in status_mod.art.DONE_VERBS
        assert rest == f"3s · {dot} 190 tokens · 7:38 PM"
        done = TurnDone(63, 0.5, Usage(output_tokens=190))
        assert " for 1m 3s · " in app._turn_note(done, at)
        stopped = TurnDone(12, 0, Usage(), status="stopped")
        assert app._turn_note(stopped, at) == "stopped · 12s · 7:38 PM"
    finally:
        await context.__aexit__(None, None, None)


def test_completed_note_uses_done_icon(clocked_status):
    status, clock, frames = clocked_status
    status.stop("Brewed for 3s", "done")
    assert frames[-1].plain == f"  {status_mod.art.icon('done')} Brewed for 3s"
    status.start()
    status.stop("stopped")
    assert frames[-1].plain == f"  {status_mod.art.icon('dot')} stopped"
