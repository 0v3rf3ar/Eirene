"""The agent loop, with a scripted provider."""

from __future__ import annotations

import asyncio

import pytest

from eirene.core import agent as agent_mod
from eirene.core.agent import (ALWAYS, Agent, Answer, Failed, NO, Notice, ToolFinished,
                               TurnDone, YES)
from eirene.core.config import Config
from eirene.core.errors import AuthError, ConnectionFailed, ProviderError
from eirene.core.modes import Mode
from eirene.core.session import Session
from eirene.providers.base import (Done, TextDelta, ThinkingDelta, ToolCall,
                                   Usage)


class Script:
    """A provider that replays canned turns."""

    supports_tools = True
    protocol = "test"

    def __init__(self, *turns):
        self.turns = list(turns)
        self.calls = 0
        self.systems: list[str] = []
        self.tools_seen: list[list | None] = []
        self.histories: list[list] = []

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        self.systems.append(system)
        self.tools_seen.append(tools)
        self.histories.append([dict(m) for m in messages])
        events = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        for event in events:
            if isinstance(event, Exception):
                raise event
            yield event

    async def models(self):
        return ["test-model"]


def build(workdir, provider, mode=Mode.AUTO, **settings):
    from eirene.tools.sandbox import Sandbox
    config = Config.load()
    for key, value in settings.items():
        config.set(key, value)
    session = Session.create(workdir)
    box = Sandbox(workdir)
    runner = Agent(session, config, box)
    runner.mode = mode
    runner.use(provider, "test", "test-model")
    return runner


def text(events) -> str:
    return "".join(e.text for e in events if isinstance(e, Answer))


async def drive(runner, prompt="go"):
    return [event async for event in runner.run(prompt)]


async def test_plain_answer(workdir):
    provider = Script([TextDelta("all "), TextDelta("done"),
                       Usage(10, 4), Done("stop")])
    runner = build(workdir, provider)
    events = await drive(runner)
    assert text(events) == "all done"
    finished = events[-1]
    assert isinstance(finished, TurnDone)
    assert finished.usage.input_tokens == 10
    assert runner.usage.output_tokens == 4


async def test_tool_call_runs_and_loops(workdir):
    provider = Script(
        [ToolCall("c1", "write_file", {"path": "out.txt", "content": "hi"}),
         Done("tool_use")],
        [TextDelta("written"), Done("stop")])
    runner = build(workdir, provider)
    events = await drive(runner)
    assert (workdir / "out.txt").read_text() == "hi"
    assert text(events) == "written"


async def test_file_change_preview_is_saved_with_the_tool_call(workdir):
    (workdir / "hello.py").write_text("print('old')\n", encoding="utf-8")
    provider = Script(
        [ToolCall("c1", "edit_file", {"path": "hello.py",
                                      "old_string": "old", "new_string": "new"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner)
    call = runner.session.messages[1]["tool_calls"][0]
    assert call["label"] == "hello.py"
    assert call["action"] == "Update"
    assert "-print('old')" in call["preview"]
    assert "+print('new')" in call["preview"]


async def test_automatic_checkpoint_is_silent_in_chat(workdir, monkeypatch):
    provider = Script(
        [ToolCall("c1", "write_file", {"path": "quiet.txt", "content": "ok"}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider)
    monkeypatch.setattr(agent_mod.git_ops, "repository", lambda path: True)
    monkeypatch.setattr(agent_mod.git_ops, "checkpoint", lambda path, label: "safe1234")

    events = await drive(runner)
    assert runner.turn_checkpoint == "safe1234"
    assert not any(isinstance(event, Notice) and "checkpoint" in event.text.lower()
                   for event in events)
    assert provider.calls == 2


async def test_tool_result_lands_in_history(workdir):
    provider = Script([ToolCall("c1", "list_dir", {"path": "."}), Done("tool_use")],
                      [TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner)
    roles = [m["role"] for m in runner.session.messages]
    assert roles == ["user", "assistant", "tool", "assistant"]
    assert runner.session.messages[1]["tool_calls"][0]["name"] == "list_dir"


async def test_manual_mode_asks_and_runs(workdir):
    provider = Script([ToolCall("c1", "write_file",
                                {"path": "a.txt", "content": "x"}), Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    asked = []

    async def approve(name, label, preview, reason):
        asked.append((name, label, preview))
        return YES

    runner.approve = approve
    await drive(runner)
    assert asked and asked[0][0] == "write_file"
    assert "+x" in asked[0][2]
    assert (workdir / "a.txt").exists()


async def test_denial_stops_the_turn(workdir):
    provider = Script([ToolCall("c1", "write_file",
                                {"path": "a.txt", "content": "x"}), Done("tool_use")],
                      [TextDelta("unreachable"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    runner.approve = lambda *args: _answer(NO)
    events = await drive(runner)
    assert not (workdir / "a.txt").exists()
    assert provider.calls == 1
    assert any(isinstance(e, Notice) and "stopped by you" in e.text for e in events)


async def test_web_address_is_shown_before_manual_approval(workdir):
    url = "https://example.test/latest"
    provider = Script([ToolCall("c1", "web_fetch", {"url": url}), Done("tool_use")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    asked = []

    async def approve(name, label, preview, reason):
        asked.append((name, label))
        return NO

    runner.approve = approve
    await drive(runner)
    assert asked == [("web_fetch", url)]


async def test_denial_still_records_a_tool_result(workdir):
    provider = Script([ToolCall("c1", "write_file", {"path": "a", "content": "x"}),
                       ToolCall("c2", "write_file", {"path": "b", "content": "y"}),
                       Done("tool_use")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    runner.approve = lambda *args: _answer(NO)
    await drive(runner)
    results = [m for m in runner.session.messages if m["role"] == "tool"]
    assert len(results) == 2, "every tool call needs a result or the API rejects it"


async def test_always_stops_asking(workdir):
    provider = Script([ToolCall("c1", "write_file", {"path": "a", "content": "x"}),
                       Done("tool_use")],
                      [ToolCall("c2", "write_file", {"path": "b", "content": "y"}),
                       Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    asked = []

    async def approve(name, label, preview, reason):
        asked.append(name)
        return ALWAYS

    runner.approve = approve
    await drive(runner)
    assert len(asked) == 1
    assert (workdir / "a").exists() and (workdir / "b").exists()


async def test_plan_mode_blocks_writes(workdir):
    provider = Script([ToolCall("c1", "write_file", {"path": "a", "content": "x"}),
                       Done("tool_use")],
                      [TextDelta("here is the plan"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.PLAN)
    events = await drive(runner)
    assert not (workdir / "a").exists()
    blocked = [e for e in events if isinstance(e, ToolFinished)]
    assert blocked[0].is_error and "blocked" in blocked[0].result


async def test_plan_mode_hides_the_shell_tool(workdir):
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.PLAN)
    await drive(runner)
    names = {spec["name"] for spec in provider.tools_seen[0]}
    assert "run_command" not in names


async def test_full_providers_receive_complete_web_workflow(workdir):
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner)
    names = {spec["name"] for spec in provider.tools_seen[0]}
    assert {"web_search", "web_fetch", "browser_inspect",
            "browser_screenshot", "read_image"} <= names
    assert "stop browsing once two reliable sources" in provider.systems[0]


async def test_a_denied_escape_never_runs_in_auto(workdir, outside):
    provider = Script([ToolCall("c1", "read_file", {"path": str(outside / "secret.txt")}),
                       Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.AUTO)
    approvals = []

    async def approve(name, label, preview, reason):
        approvals.append(reason)
        return NO

    runner.approve = approve
    events = await drive(runner)
    assert len(approvals) == 1 and "outside" in approvals[0]
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert result.is_error and "denied" in result.result


async def test_an_escape_with_nobody_to_ask_stays_blocked(workdir, outside):
    provider = Script([ToolCall("c1", "read_file", {"path": str(outside / "secret.txt")}),
                       Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.AUTO)
    runner.approve = None
    events = await drive(runner)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert result.is_error and "no one is here to approve" in result.result


async def test_an_approved_escape_actually_reaches_the_file(workdir, outside):
    secret = outside / "secret.txt"
    secret.write_text("classified\n", encoding="utf-8")
    provider = Script([ToolCall("c1", "read_file", {"path": str(secret)}),
                       Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)

    async def approve(name, label, preview, reason):
        return YES

    runner.approve = approve
    events = await drive(runner)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert not result.is_error, result.result
    assert "classified" in result.result
    assert not runner.sandbox.permitted(secret), "the sandbox must close again"


async def test_always_never_becomes_a_standing_exit_from_the_sandbox(workdir, outside):
    first, second = outside / "one.txt", outside / "two.txt"
    provider = Script([ToolCall("c1", "write_file", {"path": str(first), "content": "a"}),
                       Done("tool_use")],
                      [ToolCall("c2", "write_file", {"path": str(second), "content": "b"}),
                       Done("tool_use")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    asked = []

    async def approve(name, label, preview, reason):
        asked.append(label)
        return ALWAYS

    runner.approve = approve
    await drive(runner)
    assert len(asked) == 2, "each step outside must be approved on its own"


async def test_tool_failure_is_reported_not_raised(workdir):
    provider = Script([ToolCall("c1", "read_file", {"path": "missing.txt"}),
                       Done("tool_use")],
                      [TextDelta("recovered"), Done("stop")])
    runner = build(workdir, provider)
    events = await drive(runner)
    failures = [e for e in events if isinstance(e, ToolFinished) and e.is_error]
    assert failures and "does not exist" in failures[0].result
    assert text(events) == "recovered"


async def test_provider_error_becomes_a_failure_event(workdir):
    provider = Script([ProviderError("API key rejected")])
    runner = build(workdir, provider)
    events = await drive(runner)
    assert any(isinstance(e, Failed) and "rejected" in e.text for e in events)
    assert isinstance(events[-1], TurnDone)


async def test_iteration_cap(workdir):
    provider = Script(*[[ToolCall(f"c{n}", "write_file",
                                  {"path": f"f{n}.txt", "content": str(n)}),
                         Done("tool_use")] for n in range(6)])
    runner = build(workdir, provider, max_iterations=3)
    events = await drive(runner)
    assert provider.calls == 3
    assert any(isinstance(e, Notice) and "3 steps" in e.text for e in events)


async def test_repeated_call_guard(workdir):
    provider = Script([ToolCall("c1", "list_dir", {"path": "."}), Done("tool_use")])
    runner = build(workdir, provider, max_iterations=40)
    events = await drive(runner)
    assert provider.calls == 3
    assert any(isinstance(e, Notice) and "repeated" in e.text for e in events)


async def test_no_provider_fails_cleanly(workdir):
    runner = build(workdir, Script([Done("stop")]))
    runner.provider = None
    events = await drive(runner)
    assert isinstance(events[0], Failed)


async def test_system_prompt_carries_context(workdir):
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.PLAN)
    await drive(runner)
    system = provider.systems[0]
    assert str(workdir) in system
    assert "plan" in system
    assert "Eirene" in system
    assert "Do not introduce yourself as Codex" in system


async def test_skills_are_injected(workdir):
    from eirene.core import paths
    (paths.skills_dir() / "deploy.md").write_text("# Deploy\nUse rsync.",
                                                  encoding="utf-8")
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    runner.reload_skills()
    await drive(runner)
    assert "Use rsync." in provider.systems[0]


async def test_disabled_skills_are_not_injected(workdir):
    from eirene.core import paths
    (paths.skills_dir() / "deploy.md").write_text("# Deploy\nUse rsync.",
                                                  encoding="utf-8")
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    runner.config.set_skill("deploy", False)
    runner.reload_skills()
    await drive(runner)
    assert "rsync" not in provider.systems[0]


async def test_cancellation_propagates(workdir):
    class Slow(Script):
        async def stream(self, *args, **kwargs):
            yield TextDelta("start")
            await asyncio.sleep(10)
            yield Done("stop")

    runner = build(workdir, Slow())
    task = asyncio.create_task(drive(runner))
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_aside_does_not_touch_the_session(workdir):
    provider = Script([TextDelta("42"), Done("stop")])
    runner = build(workdir, provider)
    answer = "".join([chunk async for chunk in runner.aside("what is six times seven")])
    assert answer == "42"
    assert runner.session.messages == []


async def test_aside_uses_no_tools(workdir):
    provider = Script([TextDelta("hi"), Done("stop")])
    runner = build(workdir, provider)
    [chunk async for chunk in runner.aside("hello")]
    assert provider.tools_seen[0] is None


async def _answer(value):
    return value


async def test_missing_provider_still_ends_the_turn(workdir):
    runner = build(workdir, Script([Done("stop")]))
    runner.provider = None
    events = await drive(runner)
    assert isinstance(events[0], Failed)
    assert isinstance(events[-1], TurnDone), "the UI needs the turn to close"


async def test_a_safe_command_runs_without_asking(workdir):
    asked = []
    agent = build(workdir, Script(
        [ToolCall("c1", "run_command", {"command": "echo hi"}), Done("tool_use")],
        [TextDelta("done"), Done("stop")]), mode=Mode.MANUAL)

    async def approve(name, label, preview, reason):
        asked.append(label)
        return "no"

    agent.approve = approve

    events = [event async for event in agent.run("say hi")]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert not asked, "a read-only command must not prompt"
    assert finished and not finished[0].is_error
    assert "hi" in finished[0].result
    agent.session.close()


async def test_a_writing_command_still_asks(workdir):
    asked = []
    agent = build(workdir, Script(
        [ToolCall("c1", "run_command", {"command": "touch made.txt"}),
         Done("tool_use")],
        [TextDelta("stopped"), Done("stop")]), mode=Mode.MANUAL)

    async def approve(name, label, preview, reason):
        asked.append(label)
        return "no"

    agent.approve = approve

    events = [event async for event in agent.run("make a file")]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert asked == ["touch made.txt"]
    assert finished and finished[0].is_error
    assert not (workdir / "made.txt").exists()
    agent.session.close()


async def test_plan_mode_still_allows_reading_commands(workdir):
    agent = build(workdir, Script(
        [ToolCall("c1", "run_command", {"command": "echo peek"}), Done("tool_use")],
        [TextDelta("done"), Done("stop")]), mode=Mode.PLAN)

    events = [event async for event in agent.run("look around")]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert finished and not finished[0].is_error
    assert "peek" in finished[0].result
    agent.session.close()


async def test_a_truncated_turn_is_reported(workdir):
    agent = build(workdir, Script([TextDelta("I'll write it now."), Done("length")]))
    events = [event async for event in agent.run("write a huge file")]
    notes = [e.text for e in events if isinstance(e, Notice)]
    assert any("ran out of room" in note for note in notes)
    agent.session.close()


async def test_a_normal_turn_says_nothing_about_room(workdir):
    agent = build(workdir, Script([TextDelta("all done"), Done("stop")]))
    events = [event async for event in agent.run("small job")]
    notes = [e.text for e in events if isinstance(e, Notice)]
    assert not any("ran out of room" in note for note in notes)
    agent.session.close()


def test_max_tokens_has_room_for_a_real_file(workdir):
    from eirene.core.agent import DEFAULT_MAX_TOKENS

    agent = build(workdir, Script())
    assert agent.max_tokens == DEFAULT_MAX_TOKENS
    assert DEFAULT_MAX_TOKENS >= 16000
    agent.session.close()


def test_max_tokens_is_configurable(workdir):
    agent = build(workdir, Script(), max_tokens=40000)
    assert agent.max_tokens == 40000
    agent.session.close()


def test_a_silly_max_tokens_is_clamped(workdir):
    for value, expected in ((5, 512), (10 ** 9, 200_000), ("junk", 16384),
                            (None, 16384)):
        agent = build(workdir, Script(), max_tokens=value)
        assert agent.max_tokens == expected
        agent.session.close()


async def test_the_model_gets_the_configured_room(workdir):
    seen = {}

    class Watcher(Script):
        async def stream(self, messages, model, *, system="", tools=None,
                         max_tokens=8192):
            seen["max_tokens"] = max_tokens
            yield TextDelta("ok")
            yield Done("stop")

    agent = build(workdir, Watcher(), max_tokens=20000)
    [event async for event in agent.run("hello")]
    assert seen["max_tokens"] == 20000
    agent.session.close()


async def test_an_aside_can_see_the_conversation(workdir):
    provider = Script([TextDelta("done"), Done("stop")],
                      [TextDelta("yes"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner, "build the parser")
    [chunk async for chunk in runner.aside("what were we doing")]
    sent = provider.histories[-1]
    assert [m["role"] for m in sent] == ["user", "assistant", "user"]
    assert sent[0]["content"] == "build the parser"
    assert sent[-1]["content"] == "what were we doing"
    runner.session.close()


async def test_an_aside_leaves_the_session_alone(workdir):
    provider = Script([TextDelta("done"), Done("stop")],
                      [TextDelta("aside"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner, "first task")
    before = [dict(m) for m in runner.session.messages]
    [chunk async for chunk in runner.aside("quick question")]
    assert [dict(m) for m in runner.session.messages] == before
    runner.session.close()


async def test_a_long_chat_is_trimmed_for_an_aside(workdir):
    from eirene.core.agent import ASIDE_HISTORY
    from eirene.core.session import Message

    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    runner.session.messages = [Message.user(f"line {i}") for i in range(120)]
    [chunk async for chunk in runner.aside("still there?")]
    assert len(provider.histories[-1]) == ASIDE_HISTORY + 1


async def test_a_title_gets_room_to_think(workdir):
    from eirene.core.agent import TITLE_TOKENS

    seen = {}

    class Watcher(Script):
        async def stream(self, messages, model, *, system="", tools=None,
                         max_tokens=8192):
            seen["max_tokens"] = max_tokens
            yield TextDelta("Fixing the parser")
            yield Done("stop")

    runner = build(workdir, Watcher())
    assert await runner.title("fix the parser") == "Fixing the parser"
    assert seen["max_tokens"] == TITLE_TOKENS
    assert TITLE_TOKENS >= 256, "reasoning models need room before they answer"
    runner.session.close()


async def test_a_title_ignores_the_reasoning(workdir):
    from eirene.core.session import clean_title

    class Thinker(Script):
        async def stream(self, messages, model, **kwargs):
            yield ThinkingDelta("let me consider a good name for this")
            yield TextDelta("Creating nodejs weblog")
            yield Done("stop")

    runner = build(workdir, Thinker())
    raw = await runner.title("i want you to create a cute blog for me in nodejs")
    assert clean_title(raw) == "Creating nodejs weblog"
    runner.session.close()


async def test_the_model_can_ask_the_user_to_choose(workdir):
    asked = {}

    async def choose(question, options):
        asked["question"] = question
        asked["options"] = list(options)
        return "postgres"

    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user",
                  {"question": "which database?",
                   "options": ["sqlite", "postgres"]}), Done("tool_use")],
        [TextDelta("using postgres"), Done("stop")]), mode=Mode.MANUAL)
    agent.choose = choose

    events = [event async for event in agent.run("set up the database")]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert asked["question"] == "which database?"
    assert asked["options"] == ["sqlite", "postgres"]
    assert finished[0].result == "postgres"
    assert text(events) == "using postgres", "the turn continues after the answer"
    assert agent.session.messages[-2]["content"] == "postgres"
    agent.session.close()


async def test_auto_mode_exposes_no_question_tool(workdir):
    provider = Script([TextDelta("done"), Done("stop")])
    agent = build(workdir, provider, mode=Mode.AUTO)
    await drive(agent)
    names = {spec["name"] for spec in provider.tools_seen[0]}
    assert "ask_user" not in names
    system = provider.systems[0]
    assert "smallest sufficient number" in system
    assert "root-cause hypothesis" in system
    assert "simple work, act directly without a plan" in system


async def test_auto_mode_resolves_a_hallucinated_question_itself(workdir):
    asked = []
    provider = Script(
        [ToolCall("c1", "ask_user",
                  {"question": "which database?", "options": ["sqlite", "postgres"]}),
         Done("tool_use")],
        [TextDelta("I selected sqlite from the project constraints."), Done("stop")])
    agent = build(workdir, provider, mode=Mode.AUTO)

    async def choose(question, options):
        asked.append(question)
        return "postgres"

    agent.choose = choose
    events = await drive(agent)
    assert asked == []
    assert "selected sqlite" in text(events)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert "decide" in result.result


async def test_asking_never_prompts_for_permission(workdir):
    approvals = []

    async def approve(name, label, preview, reason):
        approvals.append(name)
        return NO

    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user", {"question": "a or b?", "options": ["a", "b"]}),
         Done("tool_use")],
        [TextDelta("done"), Done("stop")]), mode=Mode.MANUAL)
    agent.approve = approve
    agent.choose = lambda question, options: _answer("a")

    [event async for event in agent.run("go")]
    assert approvals == [], "a question is not a change; it needs no approval"
    agent.session.close()


async def test_chatting_about_it_stops_the_turn(workdir):
    from eirene.tools.registry import CHAT_OPTION

    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user", {"question": "which?", "options": ["a", "b"]}),
         Done("tool_use")],
        [TextDelta("should not run"), Done("stop")]), mode=Mode.MANUAL)
    agent.choose = lambda question, options: _answer(CHAT_OPTION)

    events = [event async for event in agent.run("go")]
    notes = [e.text for e in events if isinstance(e, Notice)]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert "talk it through" in finished[0].result
    assert any("say what you think" in note for note in notes)
    assert "should not run" not in text(events)
    agent.session.close()


async def test_dismissing_the_question_stops_the_turn(workdir):
    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user", {"question": "which?", "options": ["a", "b"]}),
         Done("tool_use")],
        [TextDelta("should not run"), Done("stop")]), mode=Mode.MANUAL)
    agent.choose = lambda question, options: _answer(None)

    events = [event async for event in agent.run("go")]
    assert "should not run" not in text(events)
    agent.session.close()


async def test_asking_with_nobody_there_carries_on(workdir):
    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user", {"question": "which?", "options": ["a", "b"]}),
         Done("tool_use")],
        [TextDelta("picked one myself"), Done("stop")]), mode=Mode.MANUAL)
    agent.choose = None

    events = [event async for event in agent.run("go")]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert "no one is here" in finished[0].result
    assert text(events) == "picked one myself"
    agent.session.close()


async def test_a_question_without_options_is_not_a_dead_end(workdir):
    agent = build(workdir, Script(
        [ToolCall("c1", "ask_user", {"question": "well?"}), Done("tool_use")],
        [TextDelta("carried on"), Done("stop")]))
    agent.choose = lambda question, options: _answer("never asked")

    events = [event async for event in agent.run("go")]
    assert text(events) == "carried on"
    agent.session.close()


def test_no_limit_by_default(workdir):
    from eirene.core.agent import DEFAULT_ITERATIONS

    assert DEFAULT_ITERATIONS == 0, "0 means the agent runs until the work is done"
    runner = build(workdir, Script())
    assert runner.iteration_limit == 0
    runner.session.close()


def test_the_limit_comes_from_the_config(workdir):
    for value, expected in ((0, 0), (5, 5), (200, 200), (-3, 0),
                            ("junk", 0), (None, 0)):
        runner = build(workdir, Script(), max_iterations=value)
        assert runner.iteration_limit == expected, value
        runner.session.close()


async def test_an_unlimited_turn_runs_past_forty_steps(workdir):
    steps = 60
    provider = Script(*[[ToolCall(f"c{n}", "write_file",
                                  {"path": f"f{n}.txt", "content": str(n)}),
                         Done("tool_use")] for n in range(steps)],
                      [TextDelta("all done"), Done("stop")])
    runner = build(workdir, provider, max_iterations=0)
    events = await drive(runner)
    assert provider.calls == steps + 1
    assert text(events) == "all done"
    assert not any(isinstance(e, Notice) and "steps" in e.text for e in events)
    assert (workdir / "f59.txt").exists()
    runner.session.close()


async def test_a_limit_still_stops_and_says_how_to_lift_it(workdir):
    provider = Script(*[[ToolCall(f"c{n}", "write_file",
                                  {"path": f"f{n}.txt", "content": str(n)}),
                         Done("tool_use")] for n in range(6)])
    runner = build(workdir, provider, max_iterations=3)
    events = await drive(runner)
    assert provider.calls == 3
    note = [e.text for e in events if isinstance(e, Notice) and "3 steps" in e.text]
    assert note, "it should say why it stopped"
    assert "max_iterations" in note[0] and "0" in note[0], "and how to lift it"
    runner.session.close()


async def test_the_repeat_guard_still_catches_a_loop_without_a_limit(workdir):
    provider = Script([ToolCall("c1", "list_dir", {"path": "."}), Done("tool_use")])
    runner = build(workdir, provider, max_iterations=0)
    events = await drive(runner)
    assert provider.calls == 3, "an identical call three times is still stopped"
    assert any(isinstance(e, Notice) and "repeated" in e.text for e in events)
    runner.session.close()


class Flaky:
    """Fails a few times before answering, like a provider that blinked."""

    supports_tools = True
    protocol = "test"

    def __init__(self, failures, error=None, partial=False):
        self.failures = failures
        self.calls = 0
        self.partial = partial
        self.error = error or ConnectionFailed("localhost:11434", "connection refused")

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        self.calls += 1
        if self.calls <= self.failures:
            if self.partial:
                yield TextDelta("half an answer")
            raise self.error
        yield TextDelta("recovered")
        yield Done("stop")

    async def models(self):
        return ["test-model"]


@pytest.fixture
def instant_retries(monkeypatch):
    monkeypatch.setattr(agent_mod, "RETRY_DELAY", 0.0)
    monkeypatch.setattr(agent_mod, "RETRY_MAX_DELAY", 0.0)


async def test_a_provider_that_blinks_is_waited_out(workdir, instant_retries):
    provider = Flaky(2)
    runner = build(workdir, provider)
    events = await drive(runner)
    assert provider.calls == 3
    assert text(events) == "recovered"
    notices = [e.text for e in events if isinstance(e, Notice)]
    assert len(notices) == 2 and "retrying" in notices[0]


async def test_a_provider_that_never_returns_stops(workdir, instant_retries):
    provider = Flaky(99)
    runner = build(workdir, provider)
    events = await drive(runner)
    assert provider.calls == agent_mod.RETRY_ATTEMPTS
    failure = next(e for e in events if isinstance(e, Failed))
    assert "cannot reach" in failure.text


async def test_retry_attempts_is_configurable(workdir, instant_retries):
    provider = Flaky(99)
    runner = build(workdir, provider, retry_attempts=2)
    await drive(runner)
    assert provider.calls == 2


async def test_a_rejected_key_is_not_retried(workdir, instant_retries):
    provider = Flaky(99, error=AuthError("API key rejected"))
    runner = build(workdir, provider)
    events = await drive(runner)
    assert provider.calls == 1, "a bad key will not fix itself"
    assert any(isinstance(e, Failed) for e in events)


async def test_a_stream_that_already_spoke_is_never_restarted(workdir, instant_retries):
    provider = Flaky(1, partial=True)
    runner = build(workdir, provider)
    events = await drive(runner)
    assert provider.calls == 1, "retrying here would duplicate the answer"
    assert text(events) == "half an answer"
    assert any(isinstance(e, Failed) for e in events)


class NativeToolProvider:
    """A provider that runs its own tools, like the headless CLIs."""

    supports_tools = False
    protocol = "test"

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        from eirene.providers.base import ProviderTool
        yield ProviderTool("t1", "Read", "calc.py", "read")
        yield ProviderTool("t1", "Read", "calc.py", "read", "def add", True, False)
        yield ProviderTool("t2", "Bash", "pytest -q", "exec")
        yield ProviderTool("t2", "Bash", "pytest -q", "exec", "boom", True, True)
        yield TextDelta("all done")
        yield Done("stop")

    async def models(self):
        return ["test-model"]


async def test_provider_run_tools_are_shown_but_never_executed(workdir):
    from eirene.core.agent import ToolStarted

    runner = build(workdir, NativeToolProvider())
    events = await drive(runner)
    started = [e for e in events if isinstance(e, ToolStarted)]
    finished = [e for e in events if isinstance(e, ToolFinished)]
    assert [(e.name, e.label, e.kind) for e in started] == [
        ("Read", "calc.py", "read"), ("Bash", "pytest -q", "exec")]
    assert [(e.name, e.result, e.is_error) for e in finished] == [
        ("Read", "def add", False), ("Bash", "boom", True)]
    assert text(events) == "all done"
    assert not any(message.get("role") == "tool" for message in runner.session.messages), \
        "Eirene must not re-run or record tools the provider already ran"


async def test_a_provider_tool_moves_the_status_line(workdir):
    from eirene.core.agent import Phase

    runner = build(workdir, NativeToolProvider())
    events = await drive(runner)
    phases = [e.name for e in events if isinstance(e, Phase)]
    assert agent_mod.RUNNING in phases, "a running command must show as running"


class OwnAgentProvider:
    """A CLI that brings its own prompt, tools and sandbox."""

    supports_tools = False
    owns_context = True
    protocol = "test"

    def __init__(self):
        self.systems = []

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        self.systems.append(system)
        yield TextDelta("done")
        yield Done("stop")

    async def models(self):
        return ["test-model"]


async def test_a_cli_provider_gets_no_eirene_prompt(workdir):
    provider = OwnAgentProvider()
    runner = build(workdir, provider)
    await drive(runner)
    sent = provider.systems[0]
    for leaked in ("Sandbox:", "run_command", "ask_user", "start_process",
                   "browser_inspect", "plan_update", "load_skill"):
        assert leaked not in sent, f"{leaked} does not exist for this provider"
    assert runner.tool_specs() is None, "Eirene must not offer it tools either"


async def test_skills_are_the_one_thing_a_cli_provider_still_gets(workdir, monkeypatch):
    from eirene.core import skills as skills_mod

    body = workdir / "demo.md"
    body.write_text("# Demo\n\nAlways rename the file to demo.txt first.\n",
                    encoding="utf-8")
    skill = skills_mod.Skill(name="demo", path=body, title="Demo",
                             summary="a demo", size=body.stat().st_size)
    provider = OwnAgentProvider()
    runner = build(workdir, provider)
    runner.skills = [skill]
    await drive(runner)
    sent = provider.systems[0]
    assert "Skill: demo" in sent
    assert "rename the file to demo.txt" in sent, "the body travels, not a pointer"
    assert "load_skill" not in sent, "it has no tool to load one with"


async def test_a_disabled_skill_is_not_sent(workdir):
    from eirene.core import skills as skills_mod

    body = workdir / "off.md"
    body.write_text("# Off\n\nsecret guidance\n", encoding="utf-8")
    skill = skills_mod.Skill(name="off", path=body, title="Off", summary="",
                             size=body.stat().st_size, enabled=False)
    provider = OwnAgentProvider()
    runner = build(workdir, provider)
    runner.skills = [skill]
    await drive(runner)
    assert "secret guidance" not in provider.systems[0]


async def test_a_normal_provider_still_gets_the_whole_prompt(workdir):
    provider = Script([TextDelta("ok"), Done("stop")])
    runner = build(workdir, provider)
    await drive(runner)
    sent = provider.systems[0]
    assert "Sandbox:" in sent and "ask_user" in sent
    assert runner.tool_specs(), "and its tools"


class WritingProvider:
    """A CLI that reports a file change with its diff."""

    supports_tools = False
    owns_context = True
    protocol = "test"

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        from eirene.providers.base import ProviderTool
        yield ProviderTool("w1", "Write", "donut.c", "write",
                           preview="--- donut.c\n+++ donut.c\n@@ -0,0 +1 @@\n+int main;")
        yield ProviderTool("w1", "Write", "donut.c", "write", "created", True, False)
        yield ProviderTool("b1", "Bash", "gcc donut.c", "exec")
        yield ProviderTool("b1", "Bash", "gcc donut.c", "exec", "ok", True, False)
        yield TextDelta("built")
        yield Done("stop")

    async def models(self):
        return ["test-model"]


async def test_a_cli_file_change_shows_the_diff_card(workdir):
    from eirene.core.agent import ToolPreview, ToolStarted

    runner = build(workdir, WritingProvider())
    events = await drive(runner)
    previews = [e for e in events if isinstance(e, ToolPreview)]
    started = [e for e in events if isinstance(e, ToolStarted)]
    assert [(e.name, e.label) for e in previews] == [("Write", "donut.c")], \
        "the write gets a diff card"
    assert "+int main;" in previews[0].diff
    assert [e.name for e in started] == ["Bash"], "a command still gets a plain card"
