"""Regressions for execution boundaries, recovery and interactive output."""
import asyncio
import shutil
import sys
import shlex
import os
from pathlib import Path

import pytest

from eirene.core import artifacts, compact, git
from eirene.core.agent import ToolFinished, ToolOutput, TurnDone
from eirene.core.errors import ToolError
from eirene.core.modes import Mode
from eirene.core.session import Session
from eirene.headless import _emit
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.tools import files, isolation, shell
from test_agent import Script, build, drive
from test_git import repo, run


def test_rollback_restores_clean_tracked_file(repo):
    checkpoint = git.checkpoint(repo)
    (repo / "tracked.txt").write_text("agent change\n")
    git.rollback(repo, checkpoint)
    assert (repo / "tracked.txt").read_text() == "original\n"


def test_rollback_preserves_index_and_unstaged_content(repo):
    target = repo / "tracked.txt"
    target.write_text("staged\n")
    run(repo, "git", "add", "tracked.txt")
    target.write_text("unstaged\n")
    checkpoint = git.checkpoint(repo)
    target.write_text("agent\n")
    run(repo, "git", "add", "tracked.txt")
    git.rollback(repo, checkpoint)
    assert target.read_text() == "unstaged\n"
    assert run(repo, "git", "show", ":tracked.txt") == "staged"


def test_rollback_rejects_later_user_edits(repo):
    checkpoint = git.checkpoint(repo)
    (repo / "tracked.txt").write_text("agent\n")
    git.seal(repo, checkpoint)
    (repo / "tracked.txt").write_text("new user work\n")
    with pytest.raises(ToolError, match="newer work"):
        git.rollback(repo, checkpoint)
    assert (repo / "tracked.txt").read_text() == "new user work\n"


def test_rollback_rejects_later_staging(repo):
    checkpoint = git.checkpoint(repo)
    (repo / "tracked.txt").write_text("agent\n")
    git.seal(repo, checkpoint)
    run(repo, "git", "add", "tracked.txt")
    with pytest.raises(ToolError, match="newer work"):
        git.rollback(repo, checkpoint)


@pytest.mark.parametrize("command", ["git branch -D main", "git config core.hooksPath hooks",
    "sort a -o b", "sort --compress-program=evil", "env python3 -c 'print(1)'",
    "./cat private", "find . -fprintf result %p", "uniq input output"])
def test_mutating_commands_never_classified_as_reads(command):
    assert not shell.is_safe(command)


async def test_plan_does_not_override_block_with_harmless(workdir):
    agent = build(workdir, Script([ToolCall("c", "run_command", {
        "command": "git branch -D main"}), Done("tool_use")], [TextDelta("done")]), mode=Mode.PLAN)
    events = await drive(agent)
    assert any(isinstance(e, ToolFinished) and "blocked" in e.result for e in events)


async def test_guard_repairs_history_and_headless_reports_failure(workdir):
    agent = build(workdir, Script([ToolCall("c", "list_dir", {"path": "."}), Done("tool_use")]))
    events = await drive(agent)
    calls = sum(len(m.get("tool_calls", [])) for m in agent.session.messages)
    results = sum(m["role"] == "tool" for m in agent.session.messages)
    assert calls == results == 3
    assert events[-1].status == "incomplete"
    assert _emit(events[-1], True)


async def test_cancellation_repairs_without_replaying_mutation(workdir, monkeypatch):
    from eirene.core import agent as agent_module
    started = asyncio.Event()
    async def execute(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(agent_module.tools, "execute", execute)
    agent = build(workdir, Script([ToolCall("c", "write_file", {"path": "a", "content": "x"})]))
    task = asyncio.create_task(drive(agent))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert agent.session.messages[-1]["role"] == "tool"
    assert "unknown" in agent.session.messages[-1]["content"]
    assert not (workdir / "a").exists()


async def test_output_is_live_and_survives_resume(workdir, monkeypatch):
    from eirene.core import agent as agent_module
    release = asyncio.Event()
    async def execute(*args, on_output=None, **kwargs):
        on_output("early output\n")
        await release.wait()
        return "complete"
    monkeypatch.setattr(agent_module.tools, "execute", execute)
    agent = build(workdir, Script([ToolCall("c", "run_command", {"command": "echo hi"})], [TextDelta("done")]))
    events = []
    async for event in agent.run("go"):
        events.append(event)
        if isinstance(event, ToolOutput) and event.chunk:
            assert not release.is_set()
            release.set()
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert artifacts.read(result.artifact_id) == "early output\n"
    agent.session.close()
    restored = Session.resume(agent.session.id)
    try:
        assert next(m for m in restored.messages if m["role"] == "tool")["artifact_id"] == result.artifact_id
    finally:
        restored.close()


async def test_parallel_reads_overlap(workdir, monkeypatch):
    from eirene.core import agent as agent_module
    count = 0
    both = asyncio.Event()
    async def execute(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 1)
        return "read"
    monkeypatch.setattr(agent_module.tools, "execute", execute)
    agent = build(workdir, Script([ToolCall("a", "list_dir", {"path": "."}),
        ToolCall("b", "list_dir", {"path": "."})], [TextDelta("done")]))
    events = await drive(agent)
    assert count == 2 and all(not e.is_error for e in events if isinstance(e, ToolFinished))


async def test_steering_skips_stale_writes(workdir):
    agent = build(workdir, Script([ToolCall("a", "write_file", {"path": "a", "content": "x"}),
        ToolCall("b", "write_file", {"path": "b", "content": "x"})], [TextDelta("adjusted")]))
    async for event in agent.run("go"):
        if isinstance(event, ToolFinished) and event.id == "a":
            agent.steer("do not create b")
    assert (workdir / "a").exists() and not (workdir / "b").exists()
    assert any(m.get("content") == "do not create b" for m in agent.session.messages)


def test_compaction_keeps_latest_constraints():
    body = compact._transcript([{"role": "user", "content": "x" * 150000},
                               {"role": "user", "content": "LATEST: preserve database"}])
    assert "LATEST: preserve database" in body


async def test_context_compaction_runs_inside_native_agent(workdir):
    calls = []
    class Provider:
        supports_tools = True
        async def stream(self, messages, model, *, system="", tools=None, **kwargs):
            calls.append((tools, list(messages)))
            yield TextDelta("summary: preserve requirements" if tools is None else "done")
            yield Done("stop")
    agent = build(workdir, Provider(), context_warning=12000)
    for _ in range(20):
        agent.session.add_user("old context " * 500)
        agent.session.add_assistant("acknowledged")
    events = await drive(agent, "continue")
    assert calls[0][0] is None and calls[1][0] is not None
    assert events[-1].status == "completed"
    assert "summary: preserve requirements" in calls[1][1][0]["content"]


async def test_external_patch_approval_scopes_permission(workdir, outside):
    target = outside / "secret.txt"
    patch = f"--- {target}\n+++ {target}\n@@ -1 +1 @@\n-do not read\n+approved\n"
    agent = build(workdir, Script([ToolCall("p", "apply_patch", {"patch": patch})], [TextDelta("done")]))
    approvals = []
    async def approve(*args):
        approvals.append(args)
        return "yes"
    agent.approve = approve
    await drive(agent)
    assert approvals and target.read_text() == "approved\n"
    assert not agent.sandbox.contains(target)


@pytest.mark.parametrize("backend", ["podman", "docker"])
def test_removed_container_backends_are_rejected(workdir, backend):
    with pytest.raises(ToolError, match="unknown isolation backend"):
        isolation.command("echo hi", workdir, backend=backend)


@pytest.mark.parametrize("backend", ["podman", "docker", "none", "bubblewrap"])
def test_legacy_backends_normalize_to_auto(backend):
    from eirene.core.config import _merge_defaults
    config = _merge_defaults({"version": 3, "execution_isolation": backend,
                              "container_image": "old-image"})
    assert config["execution_isolation"] == "auto"
    assert "container_image" not in config


def test_auto_requires_linux_even_if_container_runtime_exists(workdir, monkeypatch):
    monkeypatch.setattr(isolation.sys, "platform", "darwin")
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    with pytest.raises(ToolError, match="requires Linux"):
        isolation.command("echo hi", workdir)


async def test_sandbox_command_is_status_only(workdir):
    from types import SimpleNamespace
    from eirene.commands.sandbox import run
    from eirene.core.errors import CommandError
    messages = []
    app = SimpleNamespace(agent=SimpleNamespace(provider=SimpleNamespace(owns_context=False)),
                          sandbox=SimpleNamespace(root=workdir), theme="textual-dark", config={},
                          aside=SimpleNamespace(show_content=lambda body: messages.append(body.plain)))
    await run(app, "")
    assert "Bubblewrap" in messages[-1]
    assert "image:" not in messages[-1]
    for option in ("docker", "podman", "image alpine", "none", "auto"):
        with pytest.raises(CommandError, match="shows status"):
            await run(app, option)
    app.agent.provider.owns_context = True
    await run(app, "")
    assert "External CLI owns its sandbox" in messages[-1]


def test_old_configs_migrate_to_isolation():
    from eirene.core.config import _merge_defaults
    config = _merge_defaults({"version": 2, "execution_isolation": "none", "isolate_network": False})
    assert config["version"] == 3 and config["execution_isolation"] == "auto"
    assert config["isolate_network"] and config["auto_compact"]


def test_resume_after_torn_record_preserves_new_input(workdir):
    session = Session.create(workdir)
    session.add_user("before crash")
    session.close()
    with session.path.open("ab") as handle:
        handle.write(b'{"t":"assistant","content":"unfinished')
    restored = Session.resume(session.id)
    restored.add_user("after crash")
    restored.close()
    restored = Session.resume(session.id)
    try:
        assert [m["content"] for m in restored.messages] == ["before crash", "after crash"]
    finally:
        restored.close()


async def test_plan_can_read_approved_external_file(workdir, outside):
    agent = build(workdir, Script([ToolCall("r", "read_file", {"path": str(outside / "secret.txt")})],
                                 [TextDelta("read")]), mode=Mode.PLAN)
    approvals = []
    async def approve(*args):
        approvals.append(args)
        return "yes"
    agent.approve = approve
    events = await drive(agent)
    assert approvals
    assert any(isinstance(e, ToolFinished) and not e.is_error and "do not read" in e.result for e in events)


async def test_stream_cancellation_does_not_deadlock_on_full_queue(workdir):
    class Endless:
        supports_tools = True
        async def stream(self, *args, **kwargs):
            while True:
                yield TextDelta("x")
    agent = build(workdir, Endless())
    stream = agent._stream_once()
    await anext(stream)
    await asyncio.sleep(0.01)
    await asyncio.wait_for(stream.aclose(), 1)


def test_large_file_can_be_read_after_byte_limit(box, workdir):
    (workdir / "large.txt").write_text("x" * 100 + "\n" + ("line\n" * 100000) + "LAST\n")
    assert "LAST" in files.read_file(box, "large.txt", 100001, 1)


async def test_nested_instructions_precede_write(workdir):
    (workdir / "src").mkdir()
    (workdir / "src" / "AGENTS.md").write_text("Use explicit types.")
    agent = build(workdir, Script([ToolCall("a", "write_file", {"path": "src/a.py", "content": "x=1"})], [TextDelta("done")]))
    events = await drive(agent)
    assert not (workdir / "src" / "a.py").exists()
    assert any(isinstance(e, ToolFinished) and "Use explicit types" in e.result for e in events)


def test_isolation_fails_closed_when_backend_missing(workdir, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ToolError, match="no unsandboxed fallback"):
        isolation.command("echo x", workdir, backend="bubblewrap")


@pytest.mark.skipif(sys.platform != "linux" or not shutil.which("bwrap"), reason="Linux Bubblewrap integration")
async def test_kernel_mounts_and_environment(workdir, outside, monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "must-not-leak")
    target = outside / "secret.txt"
    command = f"test -z \"$EXAMPLE_API_KEY\" && test ! -e {shlex.quote(str(target))} && echo local > local.txt"
    result = await shell.run(command, workdir, isolation="bubblewrap", isolate_network=True)
    assert result.ok, result.output
    assert (workdir / "local.txt").read_text() == "local\n"
    result = await shell.run(f"cat {shlex.quote(str(target))}", workdir,
        isolation="bubblewrap", isolate_network=True, read_paths=[outside])
    assert result.ok and "do not read" in result.output
    result = await shell.run(f"echo changed > {shlex.quote(str(target))}", workdir,
        isolation="bubblewrap", isolate_network=True, read_paths=[outside])
    assert not result.ok and target.read_text() == "do not read"
    result = await shell.run(f"echo approved > {shlex.quote(str(target))}", workdir,
        isolation="bubblewrap", isolate_network=True, write_paths=[outside])
    assert result.ok and target.read_text() == "approved\n"
    result = await shell.run("echo forbidden > local.txt", workdir,
        isolation="bubblewrap", isolate_network=True, read_only=True)
    assert not result.ok and (workdir / "local.txt").read_text() == "local\n"


async def test_click_command_toggles_inline_saved_output(workdir):
    from test_tui import start, content
    from eirene.ui.chat import CommandBlock
    app, pilot, context = await start(workdir)
    writer = artifacts.Writer()
    writer.feed("first line\nsecond line\nthird line\nfourth line\n")
    writer.close()
    try:
        card = await app.push(CommandBlock("run_command", "echo demo"))
        card.artifact_id = writer.id
        card.finish("short result", False, 0.1)
        card.flush()
        await pilot.pause()
        assert "first line" in content(card) and "second line" in content(card)
        assert "third line" not in content(card)
        original_screen = app.screen
        await pilot.click(card, offset=(1, 0))
        await pilot.pause()
        assert app.screen is original_screen and card.expanded
        assert "third line" in content(card) and "fourth line" in content(card)
        await pilot.click(card, offset=(1, 0))
        await pilot.pause()
        assert not card.expanded and "third line" not in content(card)
    finally:
        await context.__aexit__(None, None, None)


async def test_native_approval_does_not_duplicate_highlighted_diff(workdir, monkeypatch):
    from test_tui import start
    from eirene.ui.chat import ChangeBlock, DiffBlock
    app, pilot, context = await start(workdir)
    async def approve(*args):
        return "yes"
    monkeypatch.setattr(app.permission, "ask", approve)
    patch = "--- a/demo.py\n+++ b/demo.py\n@@ -1 +1 @@\n-old\n+new\n"
    try:
        await app.push(ChangeBlock("demo.py", patch))
        assert await app._approve("native_apply_patch", "demo.py", patch, "edit") == "yes"
        assert len(app.transcript.query(ChangeBlock)) == 1
        assert not list(app.transcript.query(DiffBlock))
    finally:
        await context.__aexit__(None, None, None)


async def test_inline_output_streaming_and_missing_artifact_fallback(workdir):
    from test_tui import start, content
    from eirene.ui.chat import CommandBlock
    app, pilot, context = await start(workdir)
    try:
        card = await app.push(CommandBlock("run_command", "echo demo"))
        card.artifact_id = "missing"
        card.feed("one\ntwo\nthree\n")
        card.flush()
        assert "three" not in content(card)
        card.expanded = True
        card.feed("four\n")
        card.flush()
        assert "four" in content(card)
        card.finish("summary", False, 0)
        card.flush()
        assert card.expanded and "four" in content(card)
    finally:
        await context.__aexit__(None, None, None)
