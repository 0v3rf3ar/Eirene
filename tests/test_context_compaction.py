"""Context recycling continues long sessions and reports pressure in the UI."""

import asyncio
import json

import pytest

from eirene.core.agent import ContextCompaction, Failed
from eirene.core.session import Message
from eirene.core.usage import estimate_messages, estimate_tokens
from eirene.providers.base import Done, TextDelta
from eirene.providers.local_profile import LocalProfile


@pytest.mark.parametrize("local", [False, True], ids=["cloud", "local"])
@pytest.mark.parametrize("proactive", [False, True])
async def test_long_sessions_repeatedly_compact_and_continue(workdir, local, proactive):
    from test_agent import Script, build, drive

    class Continuing(Script):
        summaries = 0
        requests = 0

        async def isolated_stream(self, messages, model, **kwargs):
            self.summaries += 1
            if local:
                assert estimate_messages(messages) + estimate_tokens(kwargs["system"]) + kwargs["max_tokens"] < 4096
            yield TextDelta("Preserve the database and continue the tests.")
            yield Done()

        async def stream(self, messages, model, **kwargs):
            self.requests += 1
            system, specs = kwargs["system"], kwargs["tools"]
            if local:
                system, specs = self.profile.system(system), self.profile.tools(specs)
            total = estimate_messages(messages) + estimate_tokens(system) + estimate_tokens(json.dumps(specs))
            assert total + kwargs["max_tokens"] + (256 if local else 2048) <= (4096 if local else 16000)
            yield TextDelta("Completed this step. " * 50)
            yield Done()

    provider = Continuing()
    if local:
        provider.profile = LocalProfile("compact", 3, 16, 8, 0)
        async def prepare(model):
            return 4096
        provider.prepare_context = prepare
    runner = build(workdir, provider, max_tokens=1024, auto_compact=proactive,
                   model_context_limits={"test-model": 500000 if local else 16000})
    for _ in range(30):
        runner.session.add_user("Old instructions " * 500)
        runner.session.add_assistant("Earlier completed actions " * 100)
    for turn in range(12):
        # Force several boundary crossings, including when proactive compaction
        # is disabled; fresh work still reaches the model after each recycle.
        runner.session.add_assistant("Older detail " * (1800 if local else 6000))
        prompt = f"Step {turn}: preserve the database. " + "current request " * 30
        events = await drive(runner, prompt)
        assert events[-1].status == "completed", [e.text for e in events if isinstance(e, Failed)]
        assert not any(isinstance(e, Failed) for e in events)
        assert any(isinstance(e, ContextCompaction) and e.stage == "complete" for e in events)
        assert any(m.get("content") == prompt for m in runner.session.messages)
        if local:
            assert runner.context_usage()[1] == 4096
            assert provider.profile.tier == "compact"
    assert provider.requests == 12 and provider.summaries >= 12
    runner.session.close()


async def test_latest_request_larger_than_shrink_target_still_continues(workdir):
    from test_agent import Script, build
    provider = Script([TextDelta("summary"), Done()])
    runner = build(workdir, provider, max_tokens=1024,
                   model_context_limits={"test-model": 16000})
    _, budget = await runner.compaction_budget()
    for _ in range(10):
        runner.session.add_user("old " * 2000)
        runner.session.add_assistant("completed " * 500)
    latest = "L" * (int(budget * 0.75) * 4)
    runner.session.add_user(latest)
    assert estimate_messages([runner.session.messages[-1]]) > int(budget * 0.65)
    events = [e async for e in runner._budget_context()]
    assert events[-1].text.startswith("context compacted")
    assert runner.context_size() <= budget
    assert runner.session.messages[-1]["content"] == latest
    runner.session.close()


@pytest.mark.parametrize("size", [(100, 32), (40, 20)])
async def test_context_indicator_only_above_85_percent_and_above_input(workdir, size):
    from test_tui import Script, start
    from eirene.ui.status import ContextIndicator
    from eirene.ui.composer import PromptRow
    app, pilot, context = await start(workdir, Script([TextDelta("done"), Done()]), size=size)
    try:
        app.config.set("model_context_limits", {"test-model": 100000})
        indicator = app.query_one(ContextIndicator)
        app.session.messages[:] = [Message.user("x" * 340000)]
        indicator.refresh_context()
        assert not indicator.display
        app.session.messages[-1]["content"] += "xxxx"
        indicator.refresh_context()
        await pilot.pause()
        assert indicator.display
        assert "context ~85%" in indicator._Static__content.plain
        assert indicator.styles.text_align == "right"
        assert indicator.region.bottom <= app.query_one(PromptRow).region.y
        app.session.messages.clear()
        indicator.refresh_context()
        assert not indicator.display
        provider = app.agent.provider
        provider.profile = LocalProfile("compact", 3, 16, 8, 0)
        app.agent._effective_context_window = 2048
        app.session.messages[:] = [Message.user("x" * 7200)]
        indicator.refresh_context()
        assert indicator.display and "/ 2k" in indicator._Static__content.plain
    finally:
        await context.__aexit__(None, None, None)


@pytest.mark.parametrize("size", [(100, 32), (40, 20)])
@pytest.mark.parametrize("outcome", ["complete", "cancel"])
async def test_automatic_compaction_shows_small_bar_and_continues(workdir, size, outcome):
    from test_tui import Script, start
    from eirene.ui.compaction import CompactionProgress
    entered, release = asyncio.Event(), asyncio.Event()

    class Summariser(Script):
        async def isolated_stream(self, *args, **kwargs):
            entered.set()
            await release.wait()
            yield TextDelta("Summary of earlier work")
            yield Done()

    app, pilot, context = await start(workdir, Summariser([TextDelta("continued"), Done()]), size=size)
    task = None
    try:
        app.config.set("model_context_limits", {"test-model": 16000})
        app.config.set("max_tokens", 1024)
        for _ in range(20):
            app.session.add_user("question " * 500)
            app.session.add_assistant("answer " * 500)
        task = asyncio.create_task(app._run_turn("continue"))
        await asyncio.wait_for(entered.wait(), 5)
        for _ in range(3):
            await pilot.pause()
        progress = app.query_one(CompactionProgress)
        assert 0 < progress.region.width <= min(42, app.size.width)
        assert progress.region.right <= app.size.width
        assert progress.region.y >= 0 and progress.region.bottom <= app.size.height
        assert progress.parent == app.query_one("Composer")
        bar = progress.render().plain.splitlines()[-1]
        assert bar.startswith("[") and bar.endswith("]")
        assert "━" in bar and "─" in bar and len(bar) <= 32
        assert "━" in app.export_screenshot()
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            await task
        assert not app.query(CompactionProgress)
        if outcome == "complete":
            assert app.session.messages[-1]["content"] == "continued"
        else:
            assert not any(m.get("compaction_summary") for m in app.session.messages)
            assert app.session.messages[-1]["content"] == "continue"
    finally:
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await context.__aexit__(None, None, None)
