"""Approval leases end at the response boundary, including interruption."""
import asyncio

import pytest

from eirene.core.agent import ToolFinished, ToolStarted, TurnDone
from eirene.core.errors import ProviderError
from eirene.core.modes import Mode
from eirene.providers.base import Done, TextDelta, ToolCall
from test_agent import Script, build, drive


async def test_command_approval_enables_host_access_for_one_response(workdir, outside, python_command):
    first, second = outside / "first.txt", outside / "second.txt"
    command = python_command(f"from pathlib import Path; Path({str(first)!r}).write_text('installed')")
    provider = Script(
        [ToolCall("install", "run_command", {"command": command, "write_paths": [str(outside)]}), Done("tool_calls")],
        [ToolCall("verify", "read_file", {"path": str(first)}), Done("tool_calls")],
        [TextDelta("done"), Done("stop")],
        [ToolCall("next", "write_file", {"path": str(second), "content": "next"}), Done("tool_calls")],
        [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    approvals = []

    async def approve(*args):
        approvals.append(args)
        assert "until this response finishes" in args[-1]
        return "yes"

    runner.approve = approve
    async for event in runner.run("install"):
        if isinstance(event, TurnDone):
            assert runner.config.get("permissions") == "sandboxed"
    assert first.read_text() == "installed"
    assert len(approvals) == 1
    assert "This approval lasts only until" in provider.systems[1]
    assert not runner.sandbox.contains(first)
    await drive(runner, "next task")
    assert len(approvals) == 2
    assert second.read_text() == "next"
    assert runner.config.get("permissions") == "sandboxed"


@pytest.mark.parametrize("answer", ["yes", "always"])
async def test_request_full_access_tool_asks_once(workdir, outside, answer):
    target = outside / "installed.txt"
    provider = Script(
        [ToolCall("access", "request_full_access", {"reason": "Install system package"}), Done("tool_calls")],
        [ToolCall("write", "write_file", {"path": str(target), "content": "done"}), Done("tool_calls")],
        [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider)
    approvals = []

    async def approve(*args):
        approvals.append(args)
        return answer

    runner.approve = approve
    events = await drive(runner)
    assert len(approvals) == 1
    assert approvals[0][0] == "request_full_access"
    assert target.read_text() == "done"
    assert not any(e.is_error for e in events if isinstance(e, ToolFinished))
    assert runner.config.get("permissions") == "sandboxed"
    assert "request_full_access" not in runner.always


@pytest.mark.parametrize("answer", ["no", None])
async def test_denial_or_no_approver_never_grants_access(workdir, answer):
    provider = Script([ToolCall("access", "request_full_access", {"reason": "Install"}), Done("tool_calls")], [Done("stop")])
    runner = build(workdir, provider)
    if answer:
        async def approve(*args):
            return answer
        runner.approve = approve
    events = await drive(runner)
    assert any(e.is_error for e in events if isinstance(e, ToolFinished))
    assert runner.config.get("permissions") == "sandboxed"
    assert not runner.sandbox.full_access


async def test_plan_cannot_request_host_access(workdir):
    runner = build(workdir, Script([ToolCall("access", "request_full_access", {"reason": "Install"}), Done("tool_calls")], [Done("stop")]), mode=Mode.PLAN)
    async def approve(*args):
        pytest.fail("plan mode cannot ask for full access")
    runner.approve = approve
    await drive(runner)
    assert runner.config.get("permissions") == "sandboxed"
    assert "request_full_access" not in {spec["name"] for spec in runner.tool_specs()}


async def test_failure_restores_permissions(workdir):
    runner = build(workdir, Script(
        [ToolCall("access", "request_full_access", {"reason": "Install"}), Done("tool_calls")],
        [ProviderError("offline")]))
    async def approve(*args):
        return "yes"
    runner.approve = approve
    await drive(runner)
    assert runner.config.get("permissions") == "sandboxed"
    assert not runner.sandbox.full_access


async def test_workspace_write_approval_does_not_grant_host_access(workdir):
    provider = Script([ToolCall("write", "write_file", {"path": "file.txt", "content": "done"}), Done("tool_calls")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL)
    async def approve(*args):
        assert "full host access" not in args[-1]
        return "yes"
    runner.approve = approve
    await drive(runner)
    assert (workdir / "file.txt").read_text() == "done"
    assert "Permissions: sandboxed" in provider.systems[1]
    assert runner.config.get("permissions") == "sandboxed"


async def test_answering_yes_to_a_question_does_not_grant_host_access(workdir):
    provider = Script([ToolCall("question", "ask_user", {"question": "Continue?", "options": ["Yes", "No"]}), Done("tool_calls")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider)
    async def choose(*args):
        return "Yes"
    runner.choose = choose
    await drive(runner)
    assert "Permissions: sandboxed" in provider.systems[1]
    assert runner.config.get("permissions") == "sandboxed"


async def test_closing_response_early_restores_permissions(workdir):
    runner = build(workdir, Script([ToolCall("access", "request_full_access", {"reason": "Install"}), Done("tool_calls")]))
    async def approve(*args):
        return "yes"
    runner.approve = approve
    stream = runner.run("install")
    async for event in stream:
        if isinstance(event, ToolStarted):
            break
    assert runner.config.get("permissions") == "full-access"
    await stream.aclose()
    assert runner.config.get("permissions") == "sandboxed"
    assert not runner.sandbox.full_access


async def test_cancellation_stops_temporarily_unrestricted_service(workdir, python_command):
    from eirene.tools import processes
    ready = asyncio.Event()
    release = asyncio.Event()

    class Service(Script):
        async def stream(self, *args, **kwargs):
            if self.calls < 2:
                async for event in super().stream(*args, **kwargs):
                    yield event
            else:
                ready.set()
                await release.wait()

    provider = Service(
        [ToolCall("access", "request_full_access", {"reason": "Start host service"}), Done("tool_calls")],
        [ToolCall("service", "start_process", {"command": python_command("import time; time.sleep(30)")}), Done("tool_calls")])
    runner = build(workdir, provider)
    async def approve(*args):
        return "yes"
    runner.approve = approve
    task = asyncio.create_task(drive(runner))
    try:
        await asyncio.wait_for(ready.wait(), 5)
        assert processes.running()
        assert runner.config.get("permissions") == "full-access"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not processes.running()
        assert runner.config.get("permissions") == "sandboxed"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await processes.stop_all()


async def test_native_approval_uses_same_response_lease(workdir):
    class Native(Script):
        owns_context = True
        def set_context(self, root, mode, approve, choose):
            self.approve = approve
        async def stream(self, *args, **kwargs):
            assert await self.approve("run_command", "install", "", "host command") == "yes"
            assert runner.config.get("permissions") == "full-access"
            assert await self.approve("run_command", "verify", "", "host command") == "yes"
            yield TextDelta("done")
            yield Done("stop")
    runner = build(workdir, Native())
    approvals = []
    async def approve(*args):
        approvals.append(args)
        return "always"
    runner.approve = approve
    await drive(runner)
    assert len(approvals) == 1
    assert runner.config.get("permissions") == "sandboxed"


async def test_mcp_restarts_for_approved_access_and_closes_after_response(workdir, monkeypatch):
    from eirene.core import agent as agent_mod
    managers = []
    class MCP:
        def __init__(self, definitions, root):
            self.definitions = definitions
            self.closed = False
            self.errors = []
            managers.append(self)
        async def ensure(self):
            self.closed = False
        async def close(self):
            self.closed = True
        def specs(self):
            return []
        def owns(self, name):
            return name == "mcp__demo__host"
        async def call(self, name, arguments):
            assert self.definitions["demo"]["_isolation"] == "none"
            assert not self.definitions["demo"]["_isolate_network"]
            return "host task done"
    monkeypatch.setattr(agent_mod, "MCPManager", MCP)
    provider = Script([ToolCall("mcp", "mcp__demo__host", {}), Done("tool_calls")],
                      [TextDelta("done"), Done("stop")])
    runner = build(workdir, provider, mcp_servers={"demo": {"command": ["demo"]}},
                   mcp_enabled={"demo": True})
    async def approve(*args):
        return "yes"
    runner.approve = approve
    events = await drive(runner)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert not result.is_error
    assert len(managers) == 2 and all(manager.closed for manager in managers)
    assert runner.config.get("permissions") == "sandboxed"
