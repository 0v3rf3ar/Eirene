"""Release gate: verify the real default Agent command path on Windows.

This intentionally fails until AppContainer is integrated into default execution.
Approval refusal, an unused launcher, and ordinary host execution cannot pass.
Only the provider is scripted; permissions and command execution stay real.
"""

import ctypes as C
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from eirene.core.agent import ToolFinished
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.tools import processes
from eirene.tools import windows_appcontainer as appcontainer
from test_agent import Script, build, drive

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows default sandbox release gate")


@pytest.fixture
def endpoint():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def token_policy(pid):
    """Observe the real child token while it is still suspended."""
    from eirene.tools import windows_jobs

    api = appcontainer._Win32()
    handle = windows_jobs.open_process(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    api.check(handle, "OpenProcess(default sandbox check)")
    token = C.c_void_p()
    try:
        api.check(api.open_token(handle, 0x0008, C.byref(token)), "OpenProcessToken")
        is_container = api._token_value(token, 29)
        capabilities = api._token_value(token, 30)
        sid = api._token_value(token, 31)
        return (appcontainer.DWORD.from_buffer(is_container).value,
                appcontainer.DWORD.from_buffer(capabilities).value,
                bool(C.c_void_p.from_buffer(sid).value))
    finally:
        if token:
            api.close_handle(token)
        api.close_handle(handle)


async def test_default_agent_enforces_windows_kernel_sandbox(workdir, outside, monkeypatch, endpoint):
    from eirene.tools import windows_jobs

    observed = []
    original = windows_jobs.own

    def observe(pid, *args, **kwargs):
        # Observe and delegate; never substitute a process, token, or launcher.
        observed.append(token_policy(pid))
        return original(pid, *args, **kwargs)

    monkeypatch.setattr(windows_jobs, "own", observe)
    (workdir / "inside.txt").write_text("workspace input")
    result_file = workdir / "inside-result.txt"
    forbidden = outside / "forbidden.txt"

    # Use the same client against the same endpoint as a positive host control.
    host = subprocess.run([str(Path(os.environ["SystemRoot"]) / "System32" / "curl.exe"),
                           "--noproxy", "*", "--fail", "--max-time", "3", endpoint],
                          capture_output=True, timeout=10)
    assert host.returncode == 0 and host.stdout == b"ok", host.stderr

    try:
        # A script avoids conflating CMD quoting errors with denied file access.
        script = workdir / "verify-default-sandbox.cmd"
        script.write_text(
            '@echo off\n'
            'type inside.txt >nul || exit /b 10\n'
            'echo workspace-ok>inside-result.txt\n'
            'if errorlevel 1 exit /b 11\n'
            f'type "{outside / "secret.txt"}" >nul 2>nul\n'
            'if not errorlevel 1 exit /b 12\n'
            f'(echo forbidden>"{forbidden}") 2>nul\n'
            'if not errorlevel 1 exit /b 13\n'
            '"%SystemRoot%\\System32\\curl.exe" --version >nul 2>nul\n'
            'if errorlevel 1 exit /b 14\n'
            f'"%SystemRoot%\\System32\\curl.exe" --noproxy "*" --fail --connect-timeout 2 --max-time 3 {endpoint} >nul 2>nul\n'
            'if not errorlevel 1 exit /b 15\n'
            'echo default-sandbox-verified\n'
            'exit /b 0\n',
            encoding="utf-8",
        )
        runner = build(workdir, Script(
            [ToolCall("sandbox-check", "run_command", {
                "command": script.name, "shell": "cmd", "timeout": 20,
            }), Done("tool_use")],
            [TextDelta("checked"), Done("stop")],
        ))
        assert runner.config.get("permissions") == "sandboxed"
        assert runner.config.get("execution_isolation") == "auto"
        assert runner.config.get("isolate_network") is True
        assert runner.approve is None
        try:
            events = await drive(runner)
            finished = [event for event in events
                        if isinstance(event, ToolFinished) and event.id == "sandbox-check"]
            assert finished, "Eirene did not execute the default command tool"
            assert all(not event.is_error for event in finished), (
                "Eirene's default Windows command path is not sandboxed: "
                + "\n".join(event.result for event in finished)
            )
            assert observed, "No kernel token was inspected through default execution"
            assert all(policy == (1, 0, True) for policy in observed), (
                f"Default commands must have an AppContainer SID and zero capabilities: {observed}"
            )
            assert result_file.read_text().strip() == "workspace-ok"
            assert not forbidden.exists()
            assert any("default-sandbox-verified" in event.result for event in finished)
        finally:
            await processes.stop_all()
    finally:
        assert (outside / "secret.txt").read_text() == "do not read"
