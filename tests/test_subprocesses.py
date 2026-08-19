"""Cross-platform executable launch helpers."""

from eirene.core import subprocesses


def test_native_executable_is_launched_directly():
    assert subprocesses.executable_argv("tool.exe", "one") == ["tool.exe", "one"]


def test_windows_batch_shim_uses_command_processor(monkeypatch):
    monkeypatch.setattr(subprocesses, "IS_WINDOWS", True)
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")
    argv = subprocesses.executable_argv("C:\\Program Files\\tool.cmd", "a b")
    assert argv[:4] == ["C:\\Windows\\System32\\cmd.exe", "/d", "/s", "/c"]
    assert '"C:\\Program Files\\tool.cmd"' in argv[4]
    assert '"a b"' in argv[4]


def test_non_windows_batch_name_is_launched_directly(monkeypatch):
    monkeypatch.setattr(subprocesses, "IS_WINDOWS", False)
    assert subprocesses.executable_argv("tool.cmd", "one") == ["tool.cmd", "one"]
