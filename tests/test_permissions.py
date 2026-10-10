"""Host access must be explicit, effective, and reversible."""
from types import SimpleNamespace

import pytest

from eirene.commands.permissions import run
from eirene.core import platforms
from eirene.core.config import Config
from eirene.core.errors import CommandError
from eirene.core.modes import Mode
from eirene.providers.base import Done, ToolCall
from eirene.providers.claude_code import ClaudeCode
from eirene.providers.codex_subscription import CodexSubscription
from test_agent import Script, build, drive


async def test_command_restores_containment_and_does_not_persist(workdir, outside):
    runner = build(workdir, Script([]))
    messages = []
    app = SimpleNamespace(config=runner.config, sandbox=runner.sandbox,
                          agent=runner, turn=None, say=messages.append)
    await run(app, "full-access")
    assert runner.sandbox.resolve(outside / "secret.txt").exists()
    runner.config.save()
    assert Config.load().get("permissions") == "sandboxed"
    await run(app, "sandboxed")
    assert not runner.sandbox.contains(outside / "secret.txt")


@pytest.mark.parametrize("current,choice", [
    ("sandboxed", "full-access"), ("full-access", "sandboxed"),
    ("sandboxed", None), ("full-access", None),
])
async def test_permissions_picker_has_two_options_and_applies_selection(workdir, current, choice):
    runner = build(workdir, Script([]), permissions=current)
    messages = []

    async def ask_choice(title, options, *, selected):
        assert title == "permissions"
        assert [row[0] for row in options] == ["sandboxed", "full-access"]
        assert selected == current
        assert [row[0] for row in options if row[2] == "current"] == [current]
        return choice

    app = SimpleNamespace(config=runner.config, sandbox=runner.sandbox, agent=runner,
                          turn=None, say=messages.append, ask_choice=ask_choice)
    await run(app, "")
    assert runner.config.get("permissions") == (choice or current)
    assert runner.sandbox.full_access == ((choice or current) == "full-access")
    if choice is None:
        assert not messages


async def test_permissions_cannot_change_during_active_turn(workdir):
    runner = build(workdir, Script([]))
    app = SimpleNamespace(config=runner.config, sandbox=runner.sandbox,
                          agent=runner, turn=SimpleNamespace(done=lambda: False))
    with pytest.raises(CommandError, match="stop the current turn"):
        await run(app, "full-access")
    assert runner.config.get("permissions") == "sandboxed"


async def test_restoring_sandbox_stops_full_access_service(workdir, python_command):
    from eirene.tools import processes
    runner = build(workdir, Script([]), permissions="full-access")
    app = SimpleNamespace(config=runner.config, sandbox=runner.sandbox,
                          agent=runner, turn=None, say=lambda message: None)
    result = await processes.start(python_command("import time; time.sleep(30)"),
                                   workdir, owner=runner.session.id)
    process_id = result.split()[1]
    try:
        assert any(pid == process_id for _, pid in processes.running())
        await run(app, "sandboxed")
        assert not any(pid == process_id for _, pid in processes.running())
    finally:
        await processes.stop(process_id)


@pytest.mark.parametrize("mode,expected", [(Mode.MANUAL, 1), (Mode.AUTO, 0)])
async def test_full_access_preserves_mode_approval(workdir, outside, python_command, mode, expected):
    target = outside / "installed.txt"
    command = python_command(f"from pathlib import Path; Path({str(target)!r}).write_text('done')")
    provider = Script([ToolCall("host", "run_command", {"command": command}), Done("tool_calls")],
                      [Done("stop")])
    runner = build(workdir, provider, mode=mode, permissions="full-access")
    approvals = []

    async def approve(*args):
        approvals.append(args)
        return "yes"

    runner.approve = approve
    await drive(runner)
    assert target.read_text() == "done"
    assert len(approvals) == expected
    assert "Permissions: full-access" in provider.systems[0]


async def test_full_access_passes_host_execution_options(workdir, monkeypatch):
    from eirene.tools import registry
    seen = []

    async def execute(name, arguments, sandbox, **options):
        seen.append(options)
        return "done"

    monkeypatch.setattr(registry, "execute", execute)
    provider = Script([ToolCall("install", "run_command", {
        "command": "sudo -n dnf install -y cowsay"}), Done("tool_calls")], [Done("stop")])
    runner = build(workdir, provider, permissions="full-access")
    await drive(runner)
    assert seen[0]["isolation"] == "none"
    assert seen[0]["isolate_network"] is False
    assert seen[0]["read_only"] is False


async def test_plan_blocks_install_even_with_full_access(workdir):
    provider = Script([ToolCall("install", "run_command", {
        "command": "sudo -n dnf install -y cowsay"}), Done("tool_calls")], [Done("stop")])
    runner = build(workdir, provider, mode=Mode.PLAN, permissions="full-access")
    await drive(runner)
    results = [m for m in runner.session.messages if m.get("role") == "tool"]
    assert "plan mode makes no changes" in results[0]["content"]


@pytest.mark.parametrize("release,available,expected", [
    ({"ID": "fedora", "PRETTY_NAME": "Fedora Linux 44"}, ("apt-get", "dnf"), "dnf"),
    ({"ID": "fedora"}, ("dnf5",), "dnf5"),
    ({"ID": "ubuntu", "ID_LIKE": "debian"}, ("dnf", "apt-get"), "apt-get"),
    ({"ID": "rocky", "ID_LIKE": "rhel fedora"}, ("dnf",), "dnf"),
    ({"ID": "fedora"}, ("apt-get",), "unknown"),
])
def test_package_manager_uses_distribution_evidence(monkeypatch, release, available, expected):
    monkeypatch.setattr(platforms.platform, "freedesktop_os_release", lambda: release)
    assert platforms.detect_distribution("Linux", available)[1] == expected


async def test_preflight_reaches_first_model_call(workdir, monkeypatch):
    snapshot = platforms.Host("Linux", "bash", "x86_64", 4, 8, 0,
                              ("dnf",), ("apt-get",), "Fedora Linux 44", "dnf")
    monkeypatch.setattr(platforms.Host, "detect", lambda: snapshot)
    provider = Script([Done("stop")])
    runner = build(workdir, provider)
    await drive(runner)
    assert "distribution: Fedora Linux 44" in provider.systems[0]
    assert "system package manager: dnf" in provider.systems[0]
    provider.owns_context = True
    assert "system package manager: dnf" in runner.system_prompt()
    from eirene.providers.local_profile import LocalProfile
    compact = LocalProfile("compact", 3, 8, 4, 0).system(provider.systems[0])
    assert "system package manager: dnf" in compact


@pytest.mark.parametrize("provider_class", [CodexSubscription, ClaudeCode])
def test_native_full_access_and_plan_policies(provider_class, workdir):
    provider = provider_class()
    provider.set_context(workdir, "manual")
    provider.set_permissions("full-access")
    if isinstance(provider, CodexSubscription):
        assert provider._turn_policy()["sandboxPolicy"]["type"] == "dangerFullAccess"
        assert provider._thread_options("test")["sandbox"] == "danger-full-access"
        assert provider._turn_policy()["approvalPolicy"] == "untrusted"
    else:
        assert provider._permission_mode() == "manual"
    provider.set_context(workdir, "plan")
    if isinstance(provider, CodexSubscription):
        assert provider._turn_policy()["sandboxPolicy"]["type"] == "readOnly"
    else:
        assert provider._permission_mode() == "plan"
    provider.set_permissions("sandboxed")
    provider.set_context(workdir, "manual")
    if isinstance(provider, CodexSubscription):
        assert provider._turn_policy()["sandboxPolicy"]["type"] == "workspaceWrite"
    else:
        assert provider._permission_mode() == "manual"


@pytest.mark.parametrize("permissions", ["sandboxed", "full-access"])
@pytest.mark.parametrize("answer,expected", [("yes", 4), ("always", 1)])
async def test_manual_edits_need_approval_until_session_edits_allowed(workdir, permissions, answer, expected):
    provider = Script(
        [ToolCall("create", "write_file", {"path": "a.txt", "content": "a"}), Done("tool_calls")],
        [ToolCall("edit", "edit_file", {"path": "a.txt", "old_string": "a", "new_string": "b"}), Done("tool_calls")],
        [ToolCall("patch", "apply_patch", {"patch": "--- /dev/null\n+++ b.txt\n@@ -0,0 +1 @@\n+new\n"}), Done("tool_calls")],
        [Done("stop")],
        [ToolCall("next", "write_file", {"path": "c.txt", "content": "c"}), Done("tool_calls")],
        [Done("stop")])
    runner = build(workdir, provider, mode=Mode.MANUAL, permissions=permissions)
    approvals = []

    async def approve(*args):
        approvals.append(args)
        # No file may be changed until its approval callback has run.
        if len(approvals) == 1:
            assert not (workdir / "a.txt").exists()
        assert runner.config.get("permissions") == permissions
        return answer

    runner.approve = approve
    await drive(runner)
    await drive(runner, "next turn")
    assert len(approvals) == expected
    assert (workdir / "a.txt").read_text() == "b"
    assert (workdir / "b.txt").read_text() == "new\n"
    assert (workdir / "c.txt").read_text() == "c"
    assert runner.config.get("permissions") == permissions


async def test_manual_without_approver_denies_file_changes(workdir):
    runner = build(workdir, Script(
        [ToolCall("write", "write_file", {"path": "blocked.txt", "content": "x"}), Done("tool_calls")],
        [Done("stop")]), mode=Mode.MANUAL)
    await drive(runner)
    assert not (workdir / "blocked.txt").exists()


async def test_session_edit_permission_does_not_approve_commands(workdir):
    runner = build(workdir, Script(
        [ToolCall("write", "write_file", {"path": "a.txt", "content": "a"}), Done("tool_calls")],
        [ToolCall("command", "run_command", {"command": "touch unapproved.txt"}), Done("tool_calls")],
        [Done("stop")]), mode=Mode.MANUAL, permissions="full-access")
    asked = []

    async def approve(name, *args):
        asked.append(name)
        return "always" if name == "write_file" else "no"

    runner.approve = approve
    await drive(runner)
    assert asked == ["write_file", "run_command"]
    assert not (workdir / "unapproved.txt").exists()


@pytest.mark.parametrize("answer,expected", [("yes", 3), ("always", 1)])
async def test_native_manual_file_approvals_share_session_edit_permission(workdir, answer, expected):
    runner = build(workdir, Script([]), mode=Mode.MANUAL, permissions="full-access")
    asked = []

    async def approve(name, *args):
        asked.append(name)
        return answer

    runner.approve = approve
    for name in ("native_write_file", "native_edit_file", "native_apply_patch"):
        assert await runner._approve_native(name, "file.txt", "diff", "edit") == "yes"
    assert len(asked) == expected
    runner.mode = Mode.PLAN
    assert await runner._approve_native("native_write_file", "file.txt", "diff", "edit") == "no"


async def test_temporary_host_access_keeps_manual_file_prompts(workdir, outside):
    runner = build(workdir, Script(
        [ToolCall("access", "request_full_access", {"reason": "host work"}), Done("tool_calls")],
        [ToolCall("first", "write_file", {"path": str(outside / "first.txt"), "content": "first"}), Done("tool_calls")],
        [ToolCall("second", "write_file", {"path": "second.txt", "content": "second"}), Done("tool_calls")],
        [Done("stop")]), mode=Mode.MANUAL)
    asked = []

    async def approve(name, *args):
        asked.append(name)
        if name == "write_file":
            assert runner.config.get("permissions") == "full-access"
        return "yes"

    runner.approve = approve
    await drive(runner)
    assert asked == ["request_full_access", "write_file", "write_file"]
    assert (outside / "first.txt").read_text() == "first"
    assert (workdir / "second.txt").read_text() == "second"
    assert runner.config.get("permissions") == "sandboxed"


@pytest.mark.parametrize("provider_class", [CodexSubscription, ClaudeCode])
def test_native_auto_full_access_skips_approvals(provider_class, workdir):
    provider = provider_class()
    provider.set_context(workdir, "auto")
    provider.set_permissions("full-access")
    if isinstance(provider, CodexSubscription):
        policy = provider._turn_policy()
        assert policy["approvalPolicy"] == "never"
        assert policy["sandboxPolicy"]["type"] == "dangerFullAccess"
    else:
        assert provider._permission_mode() == "bypassPermissions"
