"""Native discovery semantics and bounded process supervision, without model calls."""

import asyncio
import os
import shutil
import time
from pathlib import Path

import pytest

from eirene.core.errors import ToolError
from eirene.tools import native, processes, registry, shell


@pytest.fixture(params=[False, True], ids=["preferred", "os-fallback"])
def backend(request, monkeypatch):
    if request.param:
        original = shutil.which
        monkeypatch.setattr(
            shutil, "which", lambda name: None if name == "rg" else original(name)
        )


async def test_native_search_modes(box, workdir, backend):
    (workdir / "a file.txt").write_text("before\nLogin failed\nafter\nOther\n")
    result = await native.search_text(
        box, "login failed", literal=True, case_sensitive=False, context=1
    )
    assert "a file.txt:2:Login failed" in result
    assert "before" in result and "after" in result
    names = await native.search_text(box, "Login", output="files")
    assert "a file.txt\n" in names and "failed" not in names
    counts = await native.search_text(box, "Login", output="count")
    assert "a file.txt:1" in counts
    many = await native.search_text(box, "Login", literal=True, patterns=["Other"])
    assert ":2:Login" in many and ":4:Other" in many


async def test_native_search_data_cannot_become_code(box, workdir, backend):
    name = "quote ' $() [x].txt"
    (workdir / name).write_text("literal $(touch PWNED) ' ; hi\n")
    result = await native.search_text(box, "$(touch PWNED)", literal=True)
    assert "literal" in result and not (workdir / "PWNED").exists()
    assert "literal" in await native.read_file(box, name)


async def test_native_missing_and_no_matches_differ(box, workdir, backend):
    (workdir / "a.txt").write_text("hello\n")
    assert "no matches" in await native.search_text(box, "absent")
    with pytest.raises(ToolError):
        await native.search_text(box, "hello", path="missing")


async def test_native_generated_hidden_and_excluded(box, workdir, backend):
    for name in ("src/a.py", "node_modules/a.py", ".hidden/a.py", "src/b.py"):
        p = workdir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("needle\n")
    result = await native.search_text(
        box, "needle", glob="**/*.py", exclude=["**/b.py"]
    )
    assert (
        "src/a.py" in result
        and "node_modules" not in result
        and ".hidden" not in result
        and "b.py" not in result
    )
    hidden = await native.glob_files(box, "**/*.py", hidden=True)
    assert ".hidden/a.py" in hidden


async def test_search_does_not_follow_outside_symlinks(box, workdir, outside, backend):
    try:
        (workdir / "escape").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    assert "do not read" not in await native.search_text(box, "do not read")


async def test_background_is_not_success_and_keeps_stdin(workdir, python_command):
    command = python_command(
        "import sys,time; print(sys.stdin.read(),flush=True); time.sleep(.1); print('LATE')"
    )
    result = await shell.run(
        command, workdir, input_text="DATA", execution="background", timeout=3
    )
    assert result.process_id and not result.ok
    note = await processes.poll(result.process_id, wait=True, all_output=True)
    assert "DATA" in note and "LATE" in note and "succeeded" in note


async def test_unknown_command_returns_without_waiting(workdir, python_command):
    started = time.monotonic()
    result = await shell.run(
        python_command("import time;time.sleep(10)"), workdir, yield_after=1, timeout=20
    )
    assert time.monotonic() - started < 1 and result.process_id
    await processes.stop(result.process_id)
    assert not processes._get(result.process_id).running


async def test_services_have_app_lifetime(workdir, python_command):
    note = await processes.start(python_command("import time;time.sleep(10)"), workdir)
    item = processes._get(note.split()[1])
    assert item.deadline is None and item.service and item.background
    await processes.stop_all()
    assert not item.running


async def test_cwd_and_shell_are_explicit(box, workdir):
    (workdir / "sub").mkdir()
    result = await registry.execute(
        "run_command",
        {"command": "pwd" if os.name != "nt" else "Get-Location", "cwd": "sub"},
        box,
    )
    assert "sub" in result
    with pytest.raises(Exception):
        await registry.execute("run_command", {"command": "echo no", "cwd": ".."}, box)


async def test_silent_work_is_not_automatically_stalled(workdir, python_command):
    result = await shell.run(
        python_command("import time;time.sleep(.05)"), workdir, timeout=1
    )
    assert result.ok and not result.stalled


async def test_duplicate_context_is_respected(workdir, python_command):
    command = python_command("import time;time.sleep(.1)")
    first = await shell.run(
        command, workdir, execution="background", env={"TASK_EXAMPLE": "a"}
    )
    again = await shell.run(
        command, workdir, execution="background", env={"TASK_EXAMPLE": "a"}
    )
    different = await shell.run(
        command, workdir, execution="background", env={"TASK_EXAMPLE": "b"}
    )
    assert first.process_id == again.process_id != different.process_id
    await processes.stop_all()


async def test_deadline_includes_blocked_input(workdir, python_command):
    result = await shell.run(
        python_command("import time;time.sleep(20)"),
        workdir,
        input_text="x" * 2_000_000,
        timeout=0.15,
    )
    assert result.timed_out and result.duration < 5


@pytest.mark.skipif(os.name == "nt", reason="POSIX process groups")
async def test_parent_exit_does_not_leave_output_pipe_hung(workdir):
    result = await shell.run(
        "sh -c 'sleep 20 & exit 0'", workdir, timeout=0.15, allow_blocked=True
    )
    assert result.timed_out and result.duration < 5


async def test_process_capacity_is_reserved_before_spawn(
    workdir, python_command, monkeypatch
):
    monkeypatch.setattr(processes, "MAX_PROCESSES", 1)
    result = await shell.run(
        python_command("import time;time.sleep(10)"), workdir, execution="background"
    )
    try:
        with pytest.raises(ToolError, match="at most"):
            await shell.run("echo second", workdir)
    finally:
        await processes.stop(result.process_id)


async def test_native_read_byte_continuation_after_crlf(box, workdir):
    path = workdir / "crlf.txt"
    data = "first\r\n" + ("سلام" * 2000) + "\r\n"
    path.write_bytes(data.encode())
    result = await native.read_file(box, "crlf.txt", offset=1, max_chars=700)
    assert "2\t" in result and "byte_offset=" in result
    import re

    offset = int(re.search(r"byte_offset=(\d+)", result)[1])
    continuation = await native.read_file(
        box, "crlf.txt", byte_offset=offset, max_chars=700
    )
    assert "�" not in continuation


async def test_search_respects_gitignore_without_rg(box, workdir, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("Git unavailable")
    await shell.run("git init -q", workdir)
    (workdir / ".gitignore").write_text("ignored.txt\n")
    (workdir / "ignored.txt").write_text("needle")
    (workdir / "visible.txt").write_text("needle")
    original = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda name: None if name == "rg" else original(name)
    )
    result = await native.search_text(box, "needle")
    assert "visible.txt" in result and "ignored.txt" not in result


async def test_truncated_search_never_claims_complete_absence(box, workdir):
    for i in range(10):
        (workdir / f"{i}.txt").write_text("needle\n" * 20)
    result = await native.search_text(box, "needle", limit=2)
    assert "incomplete" in result


async def test_native_templates_transport_powershell_data_through_stdin():
    payload = (
        native.ps_data({"path": "C:/quo'te/$([evil])/file"}) + "Write-Output $d.path"
    )
    assert "$([evil])" not in payload.body
    assert "$([evil])" in payload.data


@pytest.mark.skipif(
    os.name == "nt" or not shutil.which("bwrap"), reason="Linux sandbox integration"
)
async def test_subproject_cwd_keeps_workspace_visible(box, workdir):
    (workdir / "sub").mkdir()
    (workdir / "shared.txt").write_text("shared-content")
    result = await registry.execute(
        "run_command",
        {"command": "cat ../shared.txt", "cwd": "sub"},
        box,
        isolation="bubblewrap",
        isolate_network=True,
    )
    assert "shared-content" in result


async def test_reference_search_handles_dollar_identifiers(box, workdir, backend):
    (workdir / "a.js").write_text("$value = 1;\nconsole.log($value);\nvalue = 2;\n")
    result = await native.references(box, "$value")
    assert ":1:" in result and ":2:" in result and ":3:" not in result


async def test_startup_is_cancellable_without_leaving_registration(
    workdir, monkeypatch
):
    entered = asyncio.Event()

    async def stuck(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(shell, "_start", stuck)
    task = asyncio.create_task(processes.start("echo test", workdir))
    await entered.wait()
    await processes.stop_all()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not processes.running()


async def test_session_tracks_background_work_outside_workspace(workdir, python_command):
    result = await shell.run(
        python_command("import time; time.sleep(30)"),
        workdir.parent,
        owner="session-external",
        execution="background",
    )
    try:
        assert result.process_id in [
            p.id for p in processes.pending(workdir, "session-external")
        ]
        assert not processes.pending(workdir, "another-session")
    finally:
        await processes.stop(result.process_id)
