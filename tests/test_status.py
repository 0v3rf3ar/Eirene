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
