import asyncio

from eirene.core import recap
from eirene.core.config import _merge_defaults
from eirene.providers.base import Done, TextDelta
from eirene.ui.chat import RecapBlock
from test_tui import Script, content, start


def test_tracker_waits_for_two_screens_of_growth():
    tracker = recap.Tracker()
    assert not tracker.due(0, 30)
    assert not tracker.due(100, 0)
    assert not tracker.due(59, 30)
    assert tracker.due(60, 30)
    tracker.shown(60)
    assert not tracker.due(110, 30)
    assert tracker.due(120, 30)
    tracker.shown(120)
    # /clear shrank the transcript: growth is measured from the new height.
    assert not tracker.due(5, 30)
    assert not tracker.due(60, 30)
    assert tracker.due(65, 30)


def test_clean_keeps_one_complete_line():
    assert recap.clean('※ recap: "You are fixing tests;\nI found the bug. Next, run them."') == \
        "You are fixing tests; I found the bug. Next, run them."
    assert recap.clean("Too short.") == ""
    assert recap.clean("You are fixing tests and I was cut off in the middle of") == ""
    assert recap.clean("word " * 100 + ".") == ""


def test_recap_is_on_by_default_and_normalized():
    assert _merge_defaults({})["recap"] is True
    assert _merge_defaults({"recap": 0})["recap"] is False


async def test_agent_recap_uses_isolated_call_without_touching_history(workdir):
    provider = Script([TextDelta("You are adding recaps; I wired them in. Next, run the tests."),
                       Done("stop")])
    app, pilot, context = await start(workdir, provider)
    try:
        app.session.add_user("add a recap feature")
        before = list(app.session.messages)
        assert await app.agent.recap() == "You are adding recaps; I wired them in. Next, run the tests."
        assert app.session.messages == before
    finally:
        await context.__aexit__(None, None, None)


async def test_recap_shows_once_chat_grows_two_screens(workdir, monkeypatch):
    app, pilot, context = await start(workdir, Script([TextDelta("done"), Done("stop")]))
    calls = []

    async def fake_recap():
        calls.append(1)
        return "You are testing recaps; I checked the threshold. Next, review it."
    monkeypatch.setattr(app.agent, "recap", fake_recap)
    rows = {"height": 30}
    monkeypatch.setattr(app, "_transcript_height", lambda: (rows["height"], 20))
    try:
        app._offer_recap()
        await pilot.pause()
        assert not calls

        rows["height"] = 45
        app._offer_recap()
        await pilot.pause()
        await pilot.pause()
        assert calls == [1]
        blocks = [b for b in app.transcript.children if isinstance(b, RecapBlock)]
        assert len(blocks) == 1
        text = content(blocks[0])
        assert "recap: You are testing recaps" in text
        assert "(/recap off to disable)" in text

        # No repeat until another two screens of growth.
        rows["height"] = 80
        app._offer_recap()
        await pilot.pause()
        await pilot.pause()
        assert calls == [1]

        app.config.set("recap", False)
        rows["height"] = 200
        app._offer_recap()
        await pilot.pause()
        await pilot.pause()
        assert calls == [1]
    finally:
        await context.__aexit__(None, None, None)


async def test_long_real_turns_trigger_a_recap(workdir, monkeypatch):
    from test_tui import type_line
    long_reply = "\n\n".join(f"Finding {n}: a detail about the code." for n in range(40))
    app, pilot, context = await start(workdir, Script([TextDelta(long_reply), Done("stop")]))
    calls = []

    async def fake_recap():
        calls.append(1)
        return "You are reviewing the code; I reported the findings. Next, pick one to fix."
    monkeypatch.setattr(app.agent, "recap", fake_recap)
    try:
        await type_line(pilot, "list the findings")
        for _ in range(100):
            if any(isinstance(b, RecapBlock) for b in app.transcript.children):
                break
            await pilot.pause(0.05)
        assert calls == [1]
        assert any(isinstance(b, RecapBlock) for b in app.transcript.children)
    finally:
        await context.__aexit__(None, None, None)


async def test_recap_command_switches_recaps_with_the_shared_picker(workdir):
    from eirene.commands import dispatch
    from eirene.ui.picker import Picker
    app, pilot, context = await start(workdir)
    try:
        assert app.config.get("recap", True)
        command = asyncio.create_task(dispatch(app, "/recap"))
        await pilot.pause()
        picker = app.query_one(Picker)
        assert picker.waiting and picker.title == "recap"
        assert picker.options[picker.index][0] == "on", "opens on the setting in use"
        await pilot.press("down")
        await pilot.press("enter")
        await command
        assert app.config.get("recap") is False
        await dispatch(app, "/recap on")
        assert app.config.get("recap") is True
        await dispatch(app, "/recap off")
        assert app.config.get("recap") is False
        # Escape leaves the setting alone.
        command = asyncio.create_task(dispatch(app, "/recap"))
        await pilot.pause()
        await pilot.press("escape")
        await command
        assert app.config.get("recap") is False
        notices = [content(block) for block in app.transcript.children]
        assert any("recaps off" in note for note in notices)
    finally:
        await context.__aexit__(None, None, None)


async def test_recap_command_rejects_other_words(workdir):
    from eirene.commands import dispatch
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/recap maybe")
        await pilot.pause()
        assert app.config.get("recap", True)
        notices = [content(block) for block in app.transcript.children]
        assert any("/recap on or /recap off" in note for note in notices), notices
    finally:
        await context.__aexit__(None, None, None)
