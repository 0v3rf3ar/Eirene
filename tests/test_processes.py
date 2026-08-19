"""Managed long-running processes and optional PTY execution."""

from __future__ import annotations

import asyncio
import os
import shutil

import pytest

from eirene.core.errors import ToolError
from eirene.tools import processes, shell


async def test_managed_process_can_be_started_polled_and_stopped(workdir, python_command):
    note = await processes.start(
        python_command("import time\nwhile True:\n print('tick', flush=True); time.sleep(.1)"),
        workdir)
    process_id = note.split()[1]
    await asyncio.sleep(0.25)
    first = await processes.poll(process_id)
    assert "running" in first
    assert "tick" in first
    second = await processes.poll(process_id)
    assert "no new output" in second or "tick" in second
    stopped = await processes.stop(process_id)
    assert "stopped" in stopped
    assert "exited" in await processes.poll(process_id)


async def test_managed_process_keeps_bounded_output(workdir, python_command):
    note = await processes.start(python_command("print('x' * 600000)"), workdir)
    process_id = note.split()[1]
    for _ in range(50):
        await asyncio.sleep(0.02)
        if "exited" in await processes.poll(process_id):
            break
    item = processes._processes[process_id]
    assert len(item.output) <= processes.MAX_CAPTURE


async def test_managed_process_can_stop_automatically(workdir, python_command):
    note = await processes.start(python_command("import time; time.sleep(10)"), workdir,
                                 auto_stop=0.05)
    process_id = note.split()[1]
    await asyncio.sleep(0.15)
    assert "exited" in await processes.poll(process_id)
    assert not any(value == process_id for _, value in processes.running())


async def test_stop_unknown_process_is_an_error():
    with pytest.raises(ToolError, match="no managed process"):
        await processes.stop("missing")


def test_persistent_screen_allows_following_logs():
    assert shell.screen("tail -f app.log")
    assert shell.screen("tail -f app.log", persistent=True) == ""


@pytest.mark.skipif(os.name == "nt" or not shutil.which("script"),
                    reason="PTY wrapper unavailable")
async def test_pty_command_has_terminal_semantics(workdir):
    result = await shell.run("test -t 1 && echo tty", workdir, pty=True,
                             timeout=10, stall=0)
    assert result.ok
    assert "tty" in result.output
