"""Calendar snowfall and its silent, hidden session control."""

import asyncio
from datetime import date

import pytest

from eirene.app import Eirene
from eirene.commands import commands, dispatch, lookup
from eirene.ui.chat import UserBlock
from eirene.ui.snow import in_snow_season


@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 31), False),
    (date(2026, 11, 30), False),
    (date(2026, 12, 1), True),
    (date(2026, 12, 25), True),
    (date(2026, 12, 31), True),
    (date(2027, 1, 1), False),
])
def test_calendar_month(day, expected):
    assert in_snow_season(day) is expected


def test_command_is_hidden():
    assert lookup("snow").hidden
    assert "snow" not in {command.name for command in commands()}
    assert lookup("season") is None


async def test_prompt_toggle_is_silent_even_during_another_command(workdir, monkeypatch):
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: False)
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        assert snow._timer is None
        children = list(app.transcript.children)
        messages = list(app.session.messages)
        transcript_messages = app.session.transcript_messages
        saved = app.session.path.read_bytes() if app.session.path.exists() else None
        busy = asyncio.create_task(asyncio.Event().wait())
        app.command = busy
        try:
            for expected in (True, False):
                app.prompt.value = "/snow"
                await pilot.press("enter")
                await pilot.pause()
                assert (snow._timer is not None) is expected
                assert list(app.transcript.children) == children
                assert app.session.messages == messages
                assert app.session.transcript_messages == transcript_messages
                assert (app.session.path.read_bytes() if app.session.path.exists() else None) == saved
                assert app.command is busy
            await dispatch(app, "/snow")
            assert snow._timer is not None
            assert list(app.transcript.children) == children
            assert app.session.messages == messages
        finally:
            busy.cancel()
            await asyncio.gather(busy, return_exceptions=True)
    assert snow._timer is None
    assert snow._calendar_timer is None


async def test_automatic_snow_stops_for_conversation_and_override_survives_clear(workdir, monkeypatch):
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: True)
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        assert snow._timer is not None
        await app.transcript.push(UserBlock("hello"))
        assert snow._timer is None
        app.transcript.reset()
        await pilot.pause()
        assert snow._timer is not None
        snow.toggle()
        app.transcript.reset()
        await pilot.pause()
        assert snow._timer is None
        snow.toggle()
        await app.transcript.push(UserBlock("hello again"))
        await pilot.pause()
        assert snow._timer is not None
        monkeypatch.setattr("eirene.ui.snow.monotonic", lambda: snow._started + 60)
        frame = snow.render()
        assert any(0x2801 <= ord(char) <= 0x28ff for char in frame.plain)
        top = max(child.virtual_region.bottom + child.styles.margin.bottom
                  for child in app.transcript.children if child.display)
        assert not "".join(frame.plain.splitlines()[:top]).strip()


async def test_calendar_transition_and_user_preferences(workdir, monkeypatch):
    season = [False]
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: season[0])
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        assert snow._timer is None
        season[0] = True
        snow._check_calendar()
        assert snow._timer is not None
        season[0] = False
        snow._check_calendar()
        assert snow._timer is None
        app.config.set("seasonal_effects", False)
        season[0] = True
        snow._check_calendar()
        assert snow._timer is None
        app.config.set("accessible_icons", True)
        snow.toggle()
        monkeypatch.setattr("eirene.ui.snow.monotonic", lambda: snow._started + 60)
        assert "." in snow.render().plain
        assert set(snow.render().plain) <= {".", " ", "\n"}
        app.config.set("reduce_motion", True)
        app.transcript.refresh_snow()
        assert snow._timer is None


@pytest.mark.parametrize("automatic", [False, True])
async def test_snow_enters_at_top_before_falling_and_restarts_above_screen(
    workdir, monkeypatch, automatic,
):
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: automatic)
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        if not automatic:
            await dispatch(app, "/snow")
        snow._flakes = [(0.5, 0.5, 1, 0)]
        top = max((child.virtual_region.bottom + child.styles.margin.bottom
                   for child in app.transcript.children if child.display), default=0)
        available = app.transcript.content_size.height - top
        entry = available * 0.5
        now = [snow._started]
        monkeypatch.setattr("eirene.ui.snow.monotonic", lambda: now[0])

        for elapsed, expected_row in (
            (0, None), (entry - 0.25, None), (entry, top),
            (entry + 1, top + 1),
            (entry + available - 0.25, top + available - 1),
            (entry + available, top),
        ):
            now[0] = snow._started + elapsed
            rows = snow.render().plain.splitlines()
            visible_rows = [i for i, row in enumerate(rows) if row.strip()]
            assert visible_rows == ([] if expected_row is None else [expected_row])

        snow.stop()
        snow.start()
        assert not snow.render().plain.strip()


async def test_flakes_move_through_four_positions_per_terminal_row(workdir, monkeypatch):
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: True)
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        snow._flakes = [(0.5, 0, 1, 0)]
        frames = []
        for elapsed in (0, 0.25, 0.5, 0.75, 1):
            monkeypatch.setattr("eirene.ui.snow.monotonic", lambda t=elapsed: snow._started + t)
            frame = snow.render().plain
            dots = [(i, char) for i, char in enumerate(frame) if char not in " \n"]
            assert len(dots) == 1
            frames.append(dots[0])
        assert len({index for index, _ in frames[:4]}) == 1
        assert len({char for _, char in frames[:4]}) == 4
        assert frames[4][0] - frames[0][0] == app.transcript.content_size.width + 1


@pytest.mark.parametrize("ascii_icons", [False, True])
async def test_flake_stays_a_single_dot_between_steps_and_across_rows(
    workdir, monkeypatch, ascii_icons,
):
    monkeypatch.setattr("eirene.ui.snow.in_snow_season", lambda: True)
    app = Eirene(workdir)
    async with app.run_test(size=(100, 40)) as pilot:
        await pilot.pause()
        snow = app.transcript._snowfall
        snow._flakes = [(0.5, 0, 1, 0)]
        snow._ascii = ascii_icons
        for step in range(17):
            monkeypatch.setattr("eirene.ui.snow.monotonic", lambda s=step: snow._started + s / 8)
            frame = snow.render().plain
            dots = [char for char in frame if char not in " \n"]
            assert len(dots) == 1
            if ascii_icons:
                assert dots == ["."]
            else:
                assert (ord(dots[0]) - 0x2800).bit_count() == 1
