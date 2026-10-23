"""Portable policy/ownership tests and real Windows kernel containment tests."""

import ctypes as C
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from eirene.core.errors import ToolError
from eirene.tools import windows_appcontainer as sandbox


class FakeJob:
    def __init__(self, events):
        self.events = events

    def terminate(self):
        self.events.append("kill_job")

    def wait_empty(self):
        self.events.append("empty_job")

    def close(self):
        self.events.append("close_job")


class FakeAPI:
    def __init__(self, root):
        self.root = root
        self.events = []
        self.fail = ""

    def profile(self, name):
        self.events.append("profile")
        return 123

    def folder(self, sid):
        return self.root

    def suspended(self, argv, cwd, environment, sid):
        self.events.append("suspended")
        self.environment = environment
        return SimpleNamespace(process=456, thread=789, pid=12)

    def verify(self, process, sid):
        self.events.append("verify")
        if self.fail == "verify":
            raise ToolError("bad token")

    def attach(self, pid):
        self.events.append("attach")
        if self.fail == "attach":
            raise OSError("cannot assign job")
        return FakeJob(self.events)

    def resume(self, thread):
        self.events.append("resume")
        if self.fail == "resume":
            raise OSError("cannot resume")

    def close_handle(self, handle):
        self.events.append(f"close_{handle}")

    def abort(self, process):
        self.events.append("abort")

    def wait(self, process, timeout):
        self.events.append("wait")
        return 7

    def remove_profile(self, name, sid):
        self.events.append("remove_profile")


@pytest.fixture
def fake(tmp_path, monkeypatch):
    api = FakeAPI(tmp_path)
    monkeypatch.setattr(sandbox, "_Win32", lambda: api)
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    return api


def test_no_resume_before_token_verification_and_job_assignment(fake, tmp_path):
    with sandbox.AppContainer() as box:
        process = box.spawn([str(tmp_path / "cmd.exe"), "/c", "exit 7"])
        assert process.pid == 12
        assert process.wait() == 7
    events = fake.events
    assert events.index("suspended") < events.index("verify") < events.index("attach") < events.index("resume")
    assert events.index("kill_job") < events.index("empty_job") < events.index("close_job")
    assert events.index("close_456") < events.index("remove_profile")
    assert events.count("close_789") == events.count("close_456") == 1
    box.close()
    assert events.count("remove_profile") == 1
    with pytest.raises(ToolError, match="closed"):
        box.spawn([str(tmp_path / "cmd.exe")])


@pytest.mark.parametrize("failure", ["verify", "attach", "resume"])
def test_start_failure_never_falls_back_to_host_execution(fake, tmp_path, failure):
    fake.fail = failure
    with sandbox.AppContainer() as box:
        with pytest.raises((ToolError, OSError)):
            box.spawn([str(tmp_path / "cmd.exe")])
        assert "close_456" in fake.events and "close_789" in fake.events
        if failure != "resume":
            assert "resume" not in fake.events
            assert "abort" in fake.events
    assert fake.events[-1] == "remove_profile"


def test_profile_is_retained_when_process_cleanup_fails(fake, tmp_path, monkeypatch):
    box = sandbox.AppContainer()
    box.spawn([str(tmp_path / "cmd.exe")])
    def fail(*args):
        raise TimeoutError("still alive")
    monkeypatch.setattr(fake, "wait", fail)
    with pytest.raises(TimeoutError):
        box.close()
    assert not box.closed
    assert "remove_profile" not in fake.events
    monkeypatch.setattr(fake, "wait", lambda *args: 0)
    box.close()
    assert box.closed


def test_environment_never_inherits_host_secrets(fake, tmp_path, monkeypatch):
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-leak")
    monkeypatch.setenv("PYTHONPATH", "must-not-leak")
    with sandbox.AppContainer() as box:
        box.spawn([str(tmp_path / "cmd.exe")])
        values = dict(pair.split("=", 1) for pair in fake.environment.rstrip("\0").split("\0"))
        assert values["TEMP"] == str(box.home)
        assert values["PATH"] == str(tmp_path / "System32")
        assert "must-not-leak" not in fake.environment
        assert fake.environment.endswith("\0\0")


def test_unicode_command_limit_counts_utf16_units(tmp_path):
    assert "سلام" in sandbox._command_line([str(tmp_path / "app.exe"), "سلام"])
    with pytest.raises(ToolError, match="limit"):
        sandbox._command_line([str(tmp_path / "app.exe"), "😀" * 17000])


@pytest.mark.parametrize("argv", [[], ["cmd.exe"], ["bad\0exe"], [None], [123], "/app.exe"])
def test_unsafe_executable_arguments_are_rejected(argv):
    with pytest.raises(ToolError, match="absolute executable"):
        sandbox._command_line(argv)


def test_win32_abi_layout():
    if C.sizeof(C.c_void_p) == 8:
        assert C.sizeof(sandbox.StartupInfo) == 104
        assert C.sizeof(sandbox.StartupInfoEx) == 112
        assert C.sizeof(sandbox.SecurityCapabilities) == 24
        assert C.sizeof(sandbox.ProcessInfo) == 24


def test_native_creation_attributes_deny_network_and_handle_inheritance(tmp_path):
    api = sandbox._Win32.__new__(sandbox._Win32)
    events = []
    def init(attributes, count, flags, size):
        C.cast(size, C.POINTER(sandbox.SIZE))[0] = 128
        return bool(attributes)
    api.init_attributes = init
    def update(attributes, flags, key, value, size, previous, returned):
        capabilities = C.cast(value, C.POINTER(sandbox.SecurityCapabilities)).contents
        assert key == 0x00020009
        assert capabilities.sid == 123
        assert capabilities.count == 0 and not capabilities.capabilities
        assert not capabilities.reserved
        events.append("attribute")
        return True
    api.update_attribute = update
    def create(executable, command, process_security, thread_security, inherit,
               flags, environment, cwd, startup, info):
        assert executable == str(tmp_path / "app.exe")
        assert not inherit
        assert flags & 4 and flags & 0x80000 and flags & 0x400
        startup = C.cast(startup, C.POINTER(sandbox.StartupInfoEx)).contents
        assert startup.startup.cb == C.sizeof(sandbox.StartupInfoEx)
        assert not startup.startup.flags  # No inherited stdio handles either.
        assert startup.attributes
        events.append("create")
        return True
    api.create_process = create
    api.delete_attributes = lambda value: events.append("delete")
    api.suspended([str(tmp_path / "app.exe")], tmp_path, "A=B\0\0", C.c_void_p(123))
    assert events == ["attribute", "create", "delete"]


@pytest.mark.parametrize("is_container,equal_sid,capabilities", [(0, True, 0), (1, False, 0), (1, True, 1)])
def test_kernel_token_verification_rejects_wrong_identity_or_capabilities(is_container, equal_sid, capabilities):
    api = sandbox._Win32.__new__(sandbox._Win32)
    closed = []
    api.open_token = lambda *args: True
    api.close_handle = lambda token: closed.append(token)
    api.equal_sid = lambda *args: equal_sid
    buffers = {29: C.create_string_buffer(bytes(sandbox.DWORD(is_container))),
               30: C.create_string_buffer(bytes(sandbox.DWORD(capabilities))),
               31: C.create_string_buffer(bytes(C.c_void_p(123)))}
    api._token_value = lambda token, kind: buffers[kind]
    with pytest.raises(ToolError, match="verification failed"):
        api.verify(456, C.c_void_p(123))
    assert len(closed) == 1


def test_job_attachment_does_not_resume_the_process(monkeypatch):
    calls = []
    def own(pid, *, resume):
        calls.append((pid, resume))
        return "job"
    monkeypatch.setitem(sys.modules, "eirene.tools.windows_jobs", SimpleNamespace(own=own))
    api = sandbox._Win32.__new__(sandbox._Win32)
    assert api.attach(123) == "job"
    assert calls == [(123, False)]


def test_non_windows_fails_explicitly():
    if os.name == "nt":
        pytest.skip("non-Windows import contract")
    with pytest.raises(ToolError, match="requires Windows"):
        sandbox.AppContainer()


native = pytest.mark.skipif(os.name != "nt", reason="requires the real Windows kernel")


def cmd(script):
    return [str(Path(os.environ["SystemRoot"]) / "System32" / "cmd.exe"), "/d", "/s", "/c", script]


def script_command(box, script):
    # Keep CMD's script parser separate from the launcher's CRT argv quoting.
    name = uuid.uuid4().hex + ".cmd"
    (box.home / name).write_text("@echo off\n" + script + "\n")
    return cmd(name)


@native
def test_native_private_storage_and_exit_code():
    with sandbox.AppContainer() as box:
        process = box.spawn(cmd('echo sandbox>probe.txt & exit /b 7'))
        assert process.wait(15) == 7
        assert (box.home / "probe.txt").read_text().strip() == "sandbox"


@native
def test_native_outside_reads_and_writes_are_denied(tmp_path):
    secret = tmp_path / "secret.txt"
    target = tmp_path / "forbidden.txt"
    secret.write_text("secret")
    # Confirm the host can read/write; failure inside must come from isolation.
    assert secret.read_text() == "secret"
    with sandbox.AppContainer() as box:
        (box.home / "readable.txt").write_text("readable")
        assert box.spawn(cmd("type readable.txt >nul")).wait(15) == 0
        read = box.spawn(script_command(box, f'type "{secret}" >nul 2>nul && exit /b 99 || exit /b 0'))
        assert read.wait(15) == 0
        write = box.spawn(script_command(box, f'(echo forbidden>"{target}") 2>nul && exit /b 99 || exit /b 0'))
        assert write.wait(15) == 0
        assert not target.exists()


@native
def test_native_child_process_inherits_restrictions(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    with sandbox.AppContainer() as box:
        assert box.spawn(script_command(box, '"%COMSPEC%" /d /c exit /b 23')).wait(15) == 23
        # A second cmd.exe must keep the AppContainer token, with no escape.
        script = f'"%COMSPEC%" /d /c type "{secret}" >nul 2>nul && exit /b 99 || exit /b 0'
        assert box.spawn(script_command(box, script)).wait(15) == 0


@native
def test_native_timeout_and_job_cleanup():
    with sandbox.AppContainer() as box:
        # Pure cmd loop avoids relying on network access or optional utilities.
        script = box.home / "loop.cmd"
        script.write_text("@echo off\n:again\ngoto again\n")
        process = box.spawn(cmd("loop.cmd"))
        with pytest.raises(TimeoutError):
            process.wait(0.05)
        process.close()
        assert process.closed and process.returncode is not None


@native
def test_native_job_kills_child_after_parent_exits():
    with sandbox.AppContainer() as box:
        (box.home / "loop.cmd").write_text("@echo off\n:again\ngoto again\n")
        process = box.spawn(script_command(box, 'start "" /b "%COMSPEC%" /d /c loop.cmd'))
        assert process.wait(15) == 0
        with pytest.raises(TimeoutError):
            process._job.wait_empty(timeout=0)
        process.close()
        assert process.closed


@native
def test_native_profile_names_are_unique():
    with sandbox.AppContainer() as one, sandbox.AppContainer() as two:
        assert one.name != two.name and one.home != two.home
