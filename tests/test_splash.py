"""Startup logo sizing, lifecycle and input responsiveness."""
import asyncio
import time

import pytest

from eirene.app import Eirene
from eirene.core.session import Session
from eirene.ui.splash import StartupSplash, pixel_logo
from test_tui import start, content


@pytest.mark.parametrize("width,height", [(1, 1), (8, 3), (40, 20), (200, 40)])
def test_pixel_logo_fits_terminal_cells(width, height):
    from rich.cells import cell_len
    picture = pixel_logo(width, height)
    rows = picture.plain.splitlines()
    assert len(rows) <= height
    assert all(cell_len(row) <= width for row in rows)
    assert picture.spans


async def test_new_and_cleared_sessions_skip_splash(workdir):
    app, pilot, context = await start(workdir, size=(60, 24))
    try:
        assert not app.query_one(StartupSplash).display
        app.clear_session()
        await pilot.pause()
        assert not app.query_one(StartupSplash).display
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("initial", [True, False])
@pytest.mark.parametrize("load_seconds", [0, 1.1])
async def test_resume_loads_behind_splash(workdir, monkeypatch, initial, load_seconds):
    monkeypatch.setattr("eirene.ui.splash.SPLASH_SECONDS", 1)
    session = Session.create(workdir)
    session.add_user("existing conversation")
    session.close()
    original = Session.resume
    seen = []

    def resume(session_id):
        splash = app.query_one(StartupSplash)
        time.sleep(load_seconds)
        seen.append(splash.display and "▀" in content(splash))
        return original(session_id)

    app = Eirene(workdir, session.id if initial else "")
    monkeypatch.setattr(Session, "resume", resume)
    async with app.run_test(size=(60, 24)) as pilot:
        await pilot.pause()
        if not initial:
            app.run_worker(app.switch_session(session.id))
        for _ in range(200):
            splash = app.query_one(StartupSplash)
            if splash.progress == 1 and not splash.display:
                break
            await asyncio.sleep(0.01)
        assert time.monotonic() - splash._started >= 1
        assert seen == [True]
        assert app.session.messages[0]["content"] == "existing conversation"
        splash = app.query_one(StartupSplash)
        assert not splash.display
        assert splash.progress == 1
        await asyncio.sleep(0.05)
        assert splash._timer is None
        splash.display = True
        await pilot.pause()
        for width, height in [(60, 24), (32, 16)]:
            await pilot.resize_terminal(width, height)
            splash._draw()
            rows = content(splash).split("\n")
            assert len(rows) == height
            assert len(rows[-1]) == width
            assert rows[-2].strip() == "loading session 100%"
            assert rows[-1].startswith(" " * 3)
            assert rows[-1].endswith(" " * 3)
            assert set(rows[-1].strip()) == {"━"}
            picture_rows = [i for i, row in enumerate(rows) if "▀" in row]
            assert abs(picture_rows[0] - (height - 1 - picture_rows[-1])) <= 1
            for i in picture_rows:
                left = rows[i].index("▀")
                right = width - rows[i].rindex("▀") - 1
                assert abs(left - right) <= 1
        splash.finish()
        await pilot.resize_terminal(60, 24)


async def test_local_status_shows_model_without_profile_tier(workdir):
    from eirene.providers.local_profile import LocalProfile
    from test_tui import Script
    provider = Script([])
    provider.profile = LocalProfile("compact", 3, 16, 8, 0)
    app, pilot, context = await start(workdir, provider)
    try:
        app.agent.provider_key = "ollama-local"
        app.agent.model = "qwen:3b"
        app.refresh_mode_line()
        assert "ollama-local qwen:3b" in content(app.mode_line)
        assert "compact" not in content(app.mode_line)
    finally:
        await context.__aexit__(None, None, None)
