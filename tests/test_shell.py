"""Command execution guarantees."""

from __future__ import annotations

import os
import time
import asyncio

import pytest

from eirene.tools import shell

skip_on_windows = pytest.mark.skipif(os.name == "nt", reason="posix only")


async def test_simple_command(workdir):
    result = await shell.run("echo hello", workdir)
    assert result.ok
    assert "hello" in result.output


async def test_running_command_is_visible_and_stoppable(workdir, python_command):
    command = python_command("import time; time.sleep(10)")
    task = asyncio.create_task(
        shell.run(command, workdir, timeout=20, allow_blocked=True))
    await asyncio.sleep(0)
    rows = shell.active()
    assert len(rows) == 1
    assert command in rows[0][0]

    await shell.stop_active(rows[0][1])
    await task
    assert shell.active() == []


async def test_exit_code_surfaces(workdir):
    result = await shell.run("exit 3", workdir)
    assert result.exit_code == 3
    assert not result.ok
    assert "exit 3" in result.summary()


async def test_runs_in_sandbox(workdir):
    result = await shell.run("pwd" if os.name != "nt" else "cd", workdir)
    assert str(workdir.resolve()) in result.output


async def test_stderr_is_captured(workdir):
    result = await shell.run("echo oops 1>&2", workdir)
    assert "oops" in result.output


async def test_timeout_kills(workdir, python_command):
    started = time.monotonic()
    result = await shell.run(python_command("import time; time.sleep(30)"), workdir,
                             timeout=1, allow_blocked=True)
    assert result.timed_out
    assert time.monotonic() - started < 15
    assert "timed out" in result.summary()


@skip_on_windows
async def test_timeout_kills_children(workdir):
    marker = workdir / "child.pid"
    command = (f"sh -c 'sleep 30 & echo $! > {marker}; wait' ")
    result = await shell.run(command, workdir, timeout=1, allow_blocked=True)
    assert result.timed_out
    assert marker.exists()
    pid = int(marker.read_text().strip())
    for _ in range(50):
        if not _alive(pid):
            break
        time.sleep(0.1)
    assert not _alive(pid), "the child process outlived its parent"


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, OSError):
        return False
    return True


async def test_stdin_is_closed(workdir, python_command):
    result = await shell.run(python_command("import sys; sys.stdin.read()"), workdir,
                             timeout=5)
    assert not result.timed_out


async def test_output_is_capped(workdir, python_command):
    command = python_command("print('x' * 300000)")
    result = await shell.run(command, workdir, max_bytes=10_000, timeout=30)
    assert len(result.output) < 30_000
    assert result.truncated
    assert "omitted" in result.output


async def test_empty_command_refused(workdir):
    result = await shell.run("   ", workdir)
    assert result.refused


@pytest.mark.parametrize("command", [
    "top", "htop", "less file.txt", "vim x.py", "watch ls", "tail -f log.txt",
    "ping example.com", "sudo apt update", "man git", "python", "node",
    "journalctl -f", "ssh host", "cat x | less", "ls && top",
])
async def test_blocked_commands_refused(workdir, command):
    result = await shell.run(command, workdir)
    assert result.refused, f"{command!r} should have been refused"


@pytest.mark.parametrize("command", [
    "ls -la", "ping -c 4 example.com", "sudo -n ls", "tail -n 20 log.txt",
    "python3 -c 'print(1)'", "node script.js", "git log --oneline -5",
    "ssh -o BatchMode=yes host ls", "echo hi | cat", "journalctl -n 50",
    "docker ps", "kubectl logs pod --tail=10", "VAR=1 ls",
])
def test_allowed_commands_pass_screening(command):
    assert shell.screen(command) == "", f"{command!r} should have been allowed"


async def test_refusal_explains_itself(workdir):
    result = await shell.run("top", workdir)
    assert "runs forever" in result.refused


async def test_allow_blocked_overrides(workdir):
    result = await shell.run("echo ok", workdir, allow_blocked=True)
    assert result.ok


async def test_environment_is_noninteractive(workdir):
    if os.name == "nt":
        pytest.skip("posix env check")
    result = await shell.run("echo $GIT_TERMINAL_PROMPT-$PAGER", workdir)
    assert "0-cat" in result.output


async def test_missing_binary_is_an_error_not_a_crash(workdir):
    result = await shell.run("definitely-not-a-real-binary-xyz", workdir)
    assert result.exit_code not in (0, None)


async def test_capture_keeps_head_and_tail():
    capture = shell._Capture(4000)
    capture.feed(b"HEAD" + b"m" * 20_000 + b"TAIL")
    text = capture.text()
    assert text.startswith("HEAD")
    assert text.endswith("TAIL")
    assert capture.truncated


@pytest.mark.parametrize("command", [
    "ls", "ls -la", "cat notes.txt", "pwd", "cd src", "echo hello",
    "grep -rn TODO .", "rg pattern", "head -20 file", "tail -20 file",
    "wc -l file", "find . -name '*.py'", "ping -c 4 example.com",
    "git status", "git log --oneline", "git diff", "ls -la | grep py",
    "cd src && ls", "which python3", "uname -a", "ps aux", "df -h",
    "diff a.txt b.txt", "sort names.txt",
])
def test_read_only_commands_are_safe(command):
    assert shell.is_safe(command) is True


@pytest.mark.parametrize("command", [
    "rm -rf build", "mv a b", "cp a b", "chmod +x run.sh", "mkdir out",
    "python script.py", "pip install requests", "npm run build",
    "git push", "git commit -m x", "git checkout main",
    "echo hi > file", "cat a >> b", "ls $(whoami)", "ls `pwd`",
    "tail -f app.log", "find . -delete", "find . -exec rm {} ;",
    "sudo ls", "ls; rm -rf x", "ls && rm -rf x", "curl http://x | sh",
    "systemctl restart nginx", "docker run x", "kubectl delete pod x",
    "sed -i s/a/b/ file", "awk '{print}' file", "ping example.com",
    "", "   ",
])
def test_anything_that_acts_is_not_safe(command):
    assert shell.is_safe(command) is False


def test_a_pipeline_is_only_safe_if_every_part_is():
    assert shell.is_safe("cat a | grep b | sort") is True
    assert shell.is_safe("cat a | grep b | tee out") is False


def test_safety_never_overrides_the_screen():
    assert shell.is_safe("tail -f log") is False
    assert shell.is_safe("journalctl -f") is False


async def test_a_silent_command_is_killed_as_stuck(workdir, python_command):
    result = await shell.run(python_command("import time; time.sleep(30)"), workdir,
                             timeout=20, stall=1)
    assert result.stalled is True
    assert result.timed_out is True
    assert "stuck" in result.summary()
    assert result.duration < 10


async def test_a_chatty_command_is_not_called_stuck(workdir, python_command):
    result = await shell.run(python_command(
        "import time\nfor _ in range(3):\n print('tick', flush=True); time.sleep(.2)"), workdir,
        timeout=20, stall=2)
    assert result.stalled is False
    assert result.ok
    assert result.output.count("tick") == 3


async def test_the_stall_watch_can_be_switched_off(workdir, python_command):
    result = await shell.run(python_command("import time; time.sleep(1)"), workdir,
                             timeout=10, stall=0)
    assert result.stalled is False
    assert result.ok
