"""Host command contracts and connection recovery regression coverage."""
import asyncio
import base64
import json
import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from rich.cells import cell_len

from eirene.core import platforms
from eirene.core.errors import ProviderError, RateLimitError, ToolError
from eirene.providers import base
from eirene.tools import isolation, processes, shell, registry
from eirene.ui import art
from eirene.ui.status import StatusLine
from test_agent import build, Script, Flaky, drive, text
from eirene.core import agent as agent_mod
from eirene.core.agent import Notice, Failed, Phase, ToolFinished
from eirene.core.modes import Mode


@pytest.mark.parametrize("system,expected", [("Windows", "Get-Content"), ("Darwin", "BSD"), ("Linux", "Bubblewrap")])
def test_platform_contract(system, expected):
    assert expected in platforms.guidance(system=system)
    native = platforms.guidance(system=system, native=True)
    assert "run_command" not in native and "start_process" not in native and "edit_file" not in native


async def test_windows_powershell_preserves_unicode_and_reports_errors(workdir, monkeypatch):
    monkeypatch.setattr(shell, "IS_WINDOWS", True)
    monkeypatch.setattr(shell, "_spawn_kwargs", lambda: {})
    monkeypatch.setattr(shell, "own_windows", lambda process: None)
    monkeypatch.setattr("shutil.which", lambda name: "pwsh.exe" if name == "pwsh" else None)
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await shell._start("Write-Output 'سلام'; exit 7", workdir, None, True)
    args = spawn.call_args.args
    assert args[0] == "pwsh.exe" and "-NonInteractive" in args
    script = base64.b64decode(args[-1]).decode("utf-16-le")
    assert "سلام" in script and "$ErrorActionPreference='Stop'" in script
    assert "exit $LASTEXITCODE" in script


async def test_windows_cmd_selects_system_processor(workdir, monkeypatch):
    monkeypatch.setattr(shell, "IS_WINDOWS", True)
    monkeypatch.setattr(shell, "_spawn_kwargs", lambda: {})
    monkeypatch.setattr(shell, "own_windows", lambda process: None)
    monkeypatch.setenv("COMSPEC", "custom-cmd.exe")
    spawn = AsyncMock()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await shell._start('echo "a b"', workdir, None, False, shell_name='cmd')
    assert spawn.call_args.args[:4] == ("custom-cmd.exe", "/d", "/s", "/c")
    assert spawn.call_args.args[-1].endswith('echo "a b"')


async def test_missing_powershell_is_actionable(workdir, monkeypatch):
    monkeypatch.setattr(shell, "IS_WINDOWS", True)
    monkeypatch.setattr(shell, "_spawn_kwargs", lambda: {})
    monkeypatch.setattr(shell, "own_windows", lambda process: None)
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ToolError, match="PowerShell is not installed"):
        await shell._start("echo hi", workdir, None, True)


def test_process_schema_exposes_powershell():
    assert registry.BY_NAME["start_process"].schema["properties"]["powershell"]["type"] == "boolean"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX PTY launcher")
def test_macos_pty_uses_bsd_script(monkeypatch):
    monkeypatch.setattr(processes.sys, "platform", "darwin")
    monkeypatch.setattr(processes.shutil, "which", lambda name: "/usr/bin/script")
    command = processes._pty_command("printf hi")
    assert "-q /dev/null" in command and "-qefc" not in command


def test_macos_isolation_is_deny_by_default(workdir, monkeypatch):
    monkeypatch.setattr(isolation, "_mac_scratch", lambda: workdir / "scratch")
    monkeypatch.setattr(isolation.sys, "platform", "darwin")
    monkeypatch.setattr(isolation.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    argv = isolation.command("echo hi", workdir, network=False, read_only=True)
    profile = argv[2]
    quoted = json.dumps(str(workdir))
    assert argv[:2] == ["/usr/bin/sandbox-exec", "-p"]
    assert "(deny default)" in profile and "(allow network*)" not in profile
    assert f'(allow file-read* (subpath {quoted}))' in profile
    assert f'(allow file-write* (subpath {quoted}))' not in profile
    writable = isolation.command("echo hi", workdir, network=True)[2]
    assert "(allow network*)" in writable and f'(allow file-write* (subpath {quoted}))' in writable


async def test_windows_execution_requires_approval(workdir, monkeypatch):
    monkeypatch.setattr(agent_mod.platform, "system", lambda: "Windows")
    runner = build(workdir, Script([base.ToolCall("cmd", "run_command", {"command": "echo hi"}), base.Done()], [base.TextDelta("done"), base.Done()]))
    runner.approve = None
    events = await drive(runner)
    assert any(isinstance(e, ToolFinished) and e.is_error and "no one" in e.result for e in events)


async def test_windows_plan_never_launches_native_commands(workdir, monkeypatch):
    monkeypatch.setattr(agent_mod.platform, "system", lambda: "Windows")
    runner = build(workdir, Script([base.ToolCall("cmd", "language_diagnostics", {"path": "a.py"}), base.Done()], [base.TextDelta("done"), base.Done()]), mode=Mode.PLAN)
    events = await drive(runner)
    assert any(isinstance(e, ToolFinished) and "plan mode" in e.result for e in events)


async def test_slow_provider_status_keeps_same_request(workdir, monkeypatch):
    monkeypatch.setattr(agent_mod, "CONNECTION_STATUS_AFTER", .001)
    class Slow:
        supports_tools = True
        calls = 0
        async def stream(self, *args, **kwargs):
            self.calls += 1
            await asyncio.sleep(.015)
            yield base.TextDelta("ok")
            yield base.Done()
    provider = Slow()
    events = await drive(build(workdir, provider))
    assert provider.calls == 1 and text(events) == "ok"
    assert any(isinstance(e, Notice) and e.phase == "waiting for response" for e in events)


async def test_status_and_usage_do_not_disable_retry(workdir, monkeypatch):
    monkeypatch.setattr(agent_mod, "RETRY_DELAY", 0)
    provider = Script([base.ConnectionStatus("reconnecting"), base.Usage(1, 0), ProviderError("offline", retryable=True)], [base.TextDelta("ok"), base.Done()])
    events = await drive(build(workdir, provider))
    assert provider.calls == 2 and text(events) == "ok"


async def test_retry_after_is_not_shortened(workdir, monkeypatch):
    sleeps = []
    async def sleep(seconds):
        sleeps.append(seconds)
    monkeypatch.setattr(agent_mod.asyncio, "sleep", sleep)
    provider = Flaky(1, error=RateLimitError(retry_after=65))
    events = [event async for event in build(workdir, provider)._stream()]
    assert sum(sleeps) == 65
    assert any(isinstance(e, Phase) for e in events)


async def test_retry_sleep_is_cancellable(workdir):
    runner = build(workdir, Flaky(99, error=RateLimitError(retry_after=100)))
    stream = runner._stream()
    assert isinstance(await anext(stream), Notice)
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_terminal_quota_and_server_retry_header():
    with pytest.raises(ProviderError) as caught:
        base.raise_for_status(httpx.Response(429, json={"error": {"code": "insufficient_quota"}}), "api")
    assert not caught.value.retryable
    with pytest.raises(ProviderError) as caught:
        base.raise_for_status(httpx.Response(503, headers={"Retry-After": "90"}), "api")
    assert caught.value.retryable and caught.value.retry_after == 90
    assert base._retry_after(httpx.Response(429, headers={"Retry-After": "inf"})) is None
    assert base._retry_after(httpx.Response(429, headers={"Retry-After": "Wed, 01 Jan 2031 00:00:00 GMT"})) > 0


def test_three_stable_width_spinners_and_accessibility(monkeypatch):
    monkeypatch.setattr(art, "ACCESSIBLE", False)
    assert len(art.SPINNERS) == 3
    for style, frames in enumerate(art.SPINNERS):
        assert len(set(frames)) > 3
        assert all(cell_len(art.spinner_frame(t, style)) == 1 for t in range(30))
    monkeypatch.setattr(art, "ACCESSIBLE", True)
    assert all(art.spinner_frame(4, style) == "*" for style in range(3))


def test_status_picks_style_once_per_turn(monkeypatch):
    choices = iter([0, 1, 2])
    monkeypatch.setattr(art, "spinner_style", lambda: next(choices))
    status = StatusLine()
    monkeypatch.setattr(status, "update", lambda body: None)
    status.start()
    assert status._spinner_style == 1
    status._refresh()
    assert status._spinner_style == 1
    status.start()
    assert status._spinner_style == 2


def test_build_preserves_unrelated_dist_files(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("eirene_build", Path(__file__).resolve().parents[1] / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dist = tmp_path / "dist"
    dist.mkdir()
    keep = dist / "keep.txt"
    keep.write_text("keep")
    binary = dist / ("eirene.exe" if module.os.name == "nt" else "eirene")
    binary.write_text("stub")
    monkeypatch.setattr(module, "DIST", dist)
    monkeypatch.setattr(module, "WORK", tmp_path / "work")
    monkeypatch.setattr(module, "run", lambda *args: 0)
    assert module.freeze(Path(sys.executable)) == binary
    assert keep.read_text() == "keep"
