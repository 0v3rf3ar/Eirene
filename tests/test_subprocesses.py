"""Cross-platform executable launch helpers."""

from eirene.core import subprocesses
import os
import sys

import pytest


@pytest.mark.parametrize("original", [None, "", "/host/libs"])
def test_frozen_child_restores_host_loader_path(monkeypatch, original):
    from eirene.tools.shell import _child_env

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    for name in ("LD_LIBRARY_PATH", "LIBPATH"):
        monkeypatch.setenv(name, "/tmp/_MEI123/bundled-libs")
        if original is None:
            monkeypatch.delenv(name + "_ORIG", raising=False)
        else:
            monkeypatch.setenv(name + "_ORIG", original)
    env = _child_env()
    for name in ("LD_LIBRARY_PATH", "LIBPATH"):
        assert env.get(name) == original
        assert os.environ[name] == "/tmp/_MEI123/bundled-libs"
    assert _child_env({"LD_LIBRARY_PATH": "/explicit/libs"})["LD_LIBRARY_PATH"] == "/explicit/libs"


def test_source_children_keep_host_loader_path(monkeypatch):
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/host/libs")
    assert subprocesses.external_environment()["LD_LIBRARY_PATH"] == "/host/libs"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux loader and bash")
async def test_frozen_shell_starts_with_clean_loader_environment(workdir, monkeypatch):
    from eirene.tools import shell

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    result = await shell.run('printf "%s" "${LD_LIBRARY_PATH-unset}"', workdir,
                             shell_name="bash", execution="foreground")
    assert result.ok
    assert result.output == "unset"


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


@pytest.mark.skipif(sys.platform != "linux", reason="Linux loader and shell helpers")
@pytest.mark.parametrize("launcher", ["clipboard", "scheduler", "updater"])
def test_desktop_and_maintenance_children_use_host_libraries(workdir, monkeypatch, launcher):
    import shlex
    from eirene.core import updates
    from eirene.scheduling import linux_systemd
    from eirene.ui import terminal

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/_MEI123")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)
    evidence = workdir / "environment.txt"
    executable = workdir / "helper"
    executable.write_text(
        '#!/bin/sh\n'
        f'printf "%s" "${{LD_LIBRARY_PATH-unset}}" > {shlex.quote(str(evidence))}\n'
        'printf "eirene 1.2.3\\n"\n')
    executable.chmod(0o755)
    if launcher == "clipboard":
        monkeypatch.setattr(terminal, "clipboard_tool", lambda: [str(executable)])
        assert terminal.copy_to_system("text") == str(executable)
    elif launcher == "scheduler":
        assert linux_systemd._run([str(executable)]).returncode == 0
    else:
        updates._smoke_test(executable, "1.2.3")
    assert evidence.read_text() == "unset"
    assert os.environ["LD_LIBRARY_PATH"] == "/tmp/_MEI123"
