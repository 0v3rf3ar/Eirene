"""Explicit lifecycle management for long-running development processes."""

from __future__ import annotations

import asyncio
import os
import sys
import shlex
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ..core.errors import ToolError
from ..core import artifacts
from . import activity, shell

MAX_PROCESSES = 8
MAX_CAPTURE = 400_000
DEFAULT_LIFETIME = 3600


@dataclass
class ManagedProcess:
    id: str
    command: str
    cwd: Path
    process: asyncio.subprocess.Process
    started: float = field(default_factory=time.time)
    output: bytearray = field(default_factory=bytearray)
    cursor: int = 0
    pump: asyncio.Task | None = None
    stop_timer: asyncio.Task | None = None
    artifact: artifacts.Writer | None = None
    stop_reason: str = ""
    last_poll: float = 0.0

    @property
    def running(self) -> bool:
        return self.process.returncode is None or (self.pump is not None and not self.pump.done())


_processes: dict[str, ManagedProcess] = {}


async def start(command: str, cwd: Path, *, pty: bool = False, powershell: bool = False,
                isolation: str = "none", isolate_network: bool = False,
                auto_stop: float = 0, read_paths=(), write_paths=()) -> str:
    reap()
    if len([item for item in _processes.values() if item.running]) >= MAX_PROCESSES:
        raise ToolError(f"at most {MAX_PROCESSES} managed processes may run")
    reason = shell.screen(command, persistent=True)
    if reason:
        raise ToolError(reason)
    actual = _pty_command(command) if pty else command
    try:
        process = await shell._start(actual, cwd, None, powershell, stdin=subprocess.DEVNULL,
                                     isolation=isolation,
                                     isolate_network=isolate_network, read_paths=read_paths,
                                     write_paths=write_paths)
    except (OSError, ValueError) as exc:
        raise ToolError(f"cannot start process: {exc}") from exc
    try:
        process_id = adopt(process, command, cwd, auto_stop=auto_stop)
    except BaseException:
        await shell._kill_tree(process)
        raise
    await asyncio.sleep(0)
    return f"started {process_id} (pid {process.pid})"


def has_capacity() -> bool:
    reap()
    return sum(item.running for item in _processes.values()) < MAX_PROCESSES


def matching(command: str, cwd: Path) -> str | None:
    """Find an already-running command so the agent does not launch it twice."""
    return next((item.id for item in _processes.values()
                 if item.running and item.cwd == cwd and item.command == command), None)


def adopt(process, command: str, cwd: Path, *, initial_output="", auto_stop=0) -> str:
    """Take ownership of a running command without executing it a second time."""
    if not has_capacity():
        raise ToolError(f"at most {MAX_PROCESSES} managed processes may run")
    process_id = uuid.uuid4().hex[:10]
    item = ManagedProcess(process_id, command, cwd, process)
    item.artifact = artifacts.Writer()
    item.artifact.feed(initial_output)
    item.output.extend(initial_output.encode()[-MAX_CAPTURE:])
    item.cursor = len(item.output)
    _processes[process_id] = item
    lifetime = shell._clamp_timeout(auto_stop or DEFAULT_LIFETIME)
    item.pump = asyncio.create_task(_pump(item))
    item.stop_timer = asyncio.create_task(_stop_later(item, lifetime))
    activity.changed()
    return process_id


async def poll(process_id: str, *, all_output: bool = False) -> str:
    item = _get(process_id)
    # Fast empty polls should not turn into a hot model/tool loop.
    delay = min(1.0, max(0.0, item.last_poll + 1.0 - time.monotonic()))
    if delay and item.running and item.cursor == len(item.output):
        await asyncio.sleep(delay)
    item.last_poll = time.monotonic()
    await asyncio.sleep(0)
    begin = 0 if all_output else item.cursor
    data = bytes(item.output[begin:]).decode("utf-8", "replace")
    item.cursor = len(item.output)
    state = "running" if item.running else f"exited {item.process.returncode}"
    elapsed = max(time.time() - item.started, 0)
    header = f"{item.id}: {state} for {elapsed:.1f}s (pid {item.process.pid})"
    if item.stop_reason:
        header += f"; {item.stop_reason}"
    if len(data) > 6000:
        from ..core.tool_memory import compact_output
        data = compact_output(data, 6000, item.artifact.id)
    note = "\n(no new output; continue independent work before polling again)" if item.running else "\n(no new output)"
    return header + (("\n" + data.rstrip()) if data else note)


async def stop(process_id: str) -> str:
    item = _get(process_id)
    if item.running:
        await shell._kill_tree(item.process)
    if item.pump:
        try:
            await asyncio.wait_for(item.pump, timeout=2)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            item.pump.cancel()
    current = asyncio.current_task()
    if item.stop_timer and item.stop_timer is not current and not item.stop_timer.done():
        item.stop_timer.cancel()
    activity.changed()
    return f"stopped {item.id} (exit {item.process.returncode})"


def listing() -> str:
    reap()
    if not _processes:
        return "no managed processes"
    rows = []
    for item in _processes.values():
        state = "running" if item.running else f"exit {item.process.returncode}"
        rows.append(f"{item.id}  {state}  pid {item.process.pid}  {item.command}")
    return "\n".join(rows)


def reap() -> None:
    # Keep exited entries available for inspection during this app process, but
    # discard the oldest once the registry grows beyond a useful history.
    if len(_processes) <= MAX_PROCESSES * 2:
        return
    exited = sorted((p for p in _processes.values() if not p.running),
                    key=lambda p: p.started)
    for item in exited[:len(_processes) - MAX_PROCESSES * 2]:
        _processes.pop(item.id, None)


async def stop_all() -> None:
    for process_id in list(_processes):
        item = _processes[process_id]
        if item.running:
            await stop(process_id)
        elif item.stop_timer and not item.stop_timer.done():
            item.stop_timer.cancel()


def running() -> list[tuple[str, str]]:
    """Return stable picker labels and IDs for live processes."""
    reap()
    return [(f"{item.id}  pid {item.process.pid}  {item.command}", item.id)
            for item in _processes.values() if item.running]


async def _pump(item: ManagedProcess) -> None:
    try:
        await _drain(item)
    except asyncio.CancelledError:
        await shell._kill_tree(item.process)
        raise
    finally:
        if item.artifact:
            item.artifact.close()
        if item.stop_timer and not item.stop_reason and item.stop_timer is not asyncio.current_task():
            item.stop_timer.cancel()


async def _drain(item: ManagedProcess) -> None:
    stream = item.process.stdout
    if stream is None:
        await item.process.wait()
        activity.changed()
        return
    while True:
        chunk = await stream.read(8192)
        if not chunk:
            break
        item.output.extend(chunk)
        if item.artifact:
            item.artifact.feed(chunk.decode("utf-8", "replace"))
        if len(item.output) > MAX_CAPTURE:
            removed = len(item.output) - MAX_CAPTURE
            del item.output[:removed]
            item.cursor = max(item.cursor - removed, 0)
    await item.process.wait()
    activity.changed()


async def _stop_later(item: ManagedProcess, seconds: float) -> None:
    await asyncio.sleep(seconds)
    if item.running:
        item.stop_reason = "time limit reached"
        await stop(item.id)


def _get(process_id: str) -> ManagedProcess:
    item = _processes.get(process_id.strip())
    if item is None:
        raise ToolError(f"no managed process '{process_id}'")
    return item


def _pty_command(command: str) -> str:
    if os.name == "nt":
        raise ToolError("PTY mode is not available on Windows")
    executable = shutil.which("script")
    if not executable:
        raise ToolError("PTY mode needs the 'script' command")
    if sys.platform == "darwin":
        return shlex.join([executable, "-q", "/dev/null", *shell.posix_argv(command)])
    return f"{shlex.quote(executable)} -qefc {shlex.quote(command)} /dev/null"
