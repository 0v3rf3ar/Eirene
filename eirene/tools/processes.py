"""One owner, output pump, deadline and artifact for each native command."""

from __future__ import annotations

import asyncio
import codecs
import os
import sys
import shlex
import shutil
import subprocess
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

from ..core.errors import ToolError
from ..core import artifacts
from . import activity, shell

MAX_PROCESSES = 8
MAX_CAPTURE = 400_000
DEFAULT_LIFETIME = 0  # Explicit services belong to the application lifetime.
_history: OrderedDict[tuple, list[float]] = OrderedDict()


@dataclass
class ManagedProcess:
    id: str
    command: str
    cwd: Path
    process: asyncio.subprocess.Process | None = None
    started: float = field(default_factory=time.monotonic)
    output: bytearray = field(default_factory=bytearray)
    cursor: int = 0
    startup: asyncio.Task | None = None
    pump: asyncio.Task | None = None
    artifact: artifacts.Writer | None = None
    stop_reason: str = ""
    last_poll: float = 0.0
    background: bool = False
    service: bool = False
    state: str = "starting"
    deadline: float | None = None
    shell_name: str = "auto"
    context: tuple = ()
    capture: shell._Capture | None = None
    done: asyncio.Event = field(default_factory=asyncio.Event)
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    on_output: object = None
    sandbox_root: Path | None = None
    owner: str = ""
    call_id: str = ""
    notified: bool = False
    stopping: bool = False

    @property
    def running(self) -> bool:
        return not self.done.is_set()

    @property
    def exit_code(self):
        return self.process.returncode if self.process else None


_processes: dict[str, ManagedProcess] = {}


def has_capacity() -> bool:
    reap()
    return sum(item.running for item in _processes.values()) < MAX_PROCESSES


def matching(command: str, cwd: Path, context: tuple | None = None) -> str | None:
    return next(
        (
            p.id
            for p in _processes.values()
            if p.running
            and p.command == command
            and p.cwd == cwd
            and (context is None or p.context == context)
        ),
        None,
    )


def estimate(command: str, cwd: Path, shell_name: str) -> float | None:
    samples = _history.get((str(cwd), shell_name, command), [])
    if len(samples) < 3:
        return None
    return max(samples[-5:])


async def launch(
    command: str,
    cwd: Path,
    *,
    timeout: float | None,
    background=False,
    service=False,
    max_bytes=200_000,
    on_output=None,
    input_text=None,
    pty=False,
    powershell=False,
    shell_name="auto",
    isolation="none",
    isolate_network=False,
    read_paths=(),
    write_paths=(),
    read_only=False,
    env=None,
    stall=0,
    argv=None,
    owner="",
    call_id="",
    sandbox_root=None,
) -> ManagedProcess:
    context = (
        str(sandbox_root or cwd),
        owner,
        shell_name,
        powershell,
        isolation,
        isolate_network,
        read_only,
        tuple(read_paths),
        tuple(write_paths),
        input_text,
        pty,
        tuple(sorted((env or {}).items())),
    )
    existing = matching(command, cwd, context)
    if existing:
        previous = _processes[existing]
        await previous.ready.wait()
        if previous.process is None:
            raise ToolError("previous command failed during startup")
        return previous
    if not has_capacity():
        raise ToolError(
            f"at most {MAX_PROCESSES} commands may run; stop or await an existing command"
        )
    item = ManagedProcess(
        uuid.uuid4().hex[:10],
        command,
        cwd,
        background=background,
        service=service,
        shell_name=shell_name,
        context=context,
        capture=shell._Capture(max_bytes),
        on_output=on_output,
        owner=owner,
        call_id=call_id,
        sandbox_root=sandbox_root,
        startup=asyncio.current_task(),
    )
    if timeout is not None:
        item.deadline = item.started + shell._clamp_timeout(timeout)
    _processes[item.id] = item  # Reserve capacity before the first await.
    activity.changed()
    try:
        item.artifact = artifacts.Writer()
        actual = _pty_command(command) if pty else command
        spawn_limit = (
            min(10.0, max(0.01, item.deadline - time.monotonic()))
            if item.deadline
            else 10.0
        )
        item.process = await asyncio.wait_for(
            shell._start(
                actual,
                cwd,
                env,
                powershell,
                stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
                isolation=isolation,
                isolate_network=isolate_network,
                read_paths=read_paths,
                write_paths=write_paths,
                read_only=read_only,
                shell_name=shell_name,
                argv=argv,
                sandbox_root=sandbox_root,
            ),
            spawn_limit,
        )
        item.state = "running"
        item.startup = None
        item.ready.set()
        item.pump = asyncio.create_task(_supervise(item, input_text, stall))
        activity.changed()
        return item
    except BaseException:
        await _cleanup(item)
        item.state = "failed"
        item.done.set()
        item.ready.set()
        _processes.pop(item.id, None)
        activity.changed()
        raise


async def _supervise(item: ManagedProcess, input_text, stall):
    async def send_input():
        if item.process.stdin is not None:
            try:
                item.process.stdin.write((input_text or "").encode())
                await item.process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                item.process.stdin.close()

    async def communicate():
        await asyncio.gather(send_input(), _drain(item, stall))

    try:
        remaining = (
            max(0.001, item.deadline - time.monotonic()) if item.deadline else None
        )
        await asyncio.wait_for(communicate(), remaining)
        if not item.stop_reason:
            item.state = "succeeded" if item.exit_code == 0 else "failed"
    except asyncio.TimeoutError:
        item.stop_reason = "time limit reached"
        item.state = "timed_out"
    except asyncio.CancelledError:
        item.stop_reason = item.stop_reason or "cancelled"
        item.state = "cancelled" if item.state != "timed_out" else item.state
    except Exception as exc:
        item.stop_reason = f"output failed: {exc}"
        item.state = "failed"
    finally:
        await _cleanup(item)
        if item.state == "succeeded":
            key = (str(item.cwd), item.shell_name, item.command)
            samples = _history.setdefault(key, [])
            samples.append(time.monotonic() - item.started)
            del samples[:-5]
            _history.move_to_end(key)
            while len(_history) > 128:
                _history.popitem(last=False)
        item.done.set()
        activity.changed()


async def _cleanup(item):
    try:
        if item.process:
            await asyncio.wait_for(shell._kill_tree(item.process), 4)
            if item.process.returncode is None:
                raise OSError("OS process could not be reaped")
    except (OSError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
        item.stop_reason += f"; cleanup incomplete: {exc or 'deadline exceeded'}"
        if item.state == "succeeded":
            item.state = "failed"
    finally:
        if item.process:
            shell.release_process(item.process)
        if item.artifact:
            try:
                item.artifact.close()
            except OSError as exc:
                item.stop_reason += f"; output close failed: {exc}"
                item.state = "failed"


async def _drain(item: ManagedProcess, stall=0):
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        read = item.process.stdout.read(8192)
        chunk = await asyncio.wait_for(read, stall) if stall else await read
        if not chunk:
            break
        item.capture.feed(chunk)
        item.output.extend(chunk)
        if len(item.output) > MAX_CAPTURE:
            removed = len(item.output) - MAX_CAPTURE
            del item.output[:removed]
            item.cursor = max(0, item.cursor - removed)
        text = decoder.decode(chunk)
        item.artifact.feed(text)
        if item.on_output and not item.background:
            item.on_output(text)
    final = decoder.decode(b"", final=True)
    if final:
        item.artifact.feed(final)
    await item.process.wait()


def background(item: ManagedProcess) -> None:
    item.background = True
    item.cursor = len(item.output)
    item.on_output = None
    activity.changed()


async def start(
    command: str,
    cwd: Path,
    *,
    pty=False,
    powershell=False,
    isolation="none",
    isolate_network=False,
    auto_stop=0,
    read_paths=(),
    write_paths=(),
    shell_name="auto",
    owner="",
    call_id="",
    sandbox_root=None,
) -> str:
    reason = shell.screen(command, persistent=True)
    if reason:
        raise ToolError(reason)
    item = await launch(
        command,
        cwd,
        timeout=auto_stop or None,
        background=True,
        service=True,
        pty=pty,
        powershell=powershell,
        shell_name=shell_name,
        isolation=isolation,
        isolate_network=isolate_network,
        read_paths=read_paths,
        write_paths=write_paths,
        owner=owner,
        call_id=call_id,
        sandbox_root=sandbox_root,
    )
    return (
        f"started {item.id} (pid {item.process.pid}); service owned until app exit"
        + (f"; deadline {auto_stop:g}s" if auto_stop else "")
    )


async def poll(process_id: str, *, all_output=False, wait=False) -> str:
    item = _get(process_id)
    if wait and item.running:
        await item.done.wait()
    begin = 0 if all_output else item.cursor
    data = bytes(item.output[begin:]).decode("utf-8", "replace")
    item.cursor = len(item.output)
    state = "running" if item.running else f"exited {item.exit_code}; {item.state}"
    header = f"{item.id}: {state} for {time.monotonic() - item.started:.1f}s"
    if item.stop_reason:
        header += f"; {item.stop_reason}"
    if len(data) > 6000:
        from ..core.tool_memory import compact_output

        data = compact_output(data, 6000, item.artifact.id)
    if item.artifact:
        header += f"; output artifact {item.artifact.id}"
    return header + ("\n" + data.rstrip() if data else "\n(no new output)")


async def stop(process_id: str) -> str:
    item = _get(process_id)
    if item.running and not item.stopping:
        item.stopping = True
        item.stop_reason = "cancelled"
        if item.pump:
            await asyncio.sleep(0)  # Let the supervisor enter its cleanup boundary.
            item.pump.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(item.pump), 5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                item.stop_reason = "cleanup did not finish within 5s"
        elif item.startup and item.startup is not asyncio.current_task():
            item.startup.cancel()
            try:
                await asyncio.wait_for(item.done.wait(), 5)
            except asyncio.TimeoutError:
                item.stop_reason = "startup cleanup did not finish within 5s"
        elif item.process:
            await shell._kill_tree(item.process)
    activity.changed()
    return f"stopped {item.id} (exit {item.exit_code}); {item.stop_reason}"


def listing() -> str:
    reap()
    return (
        "\n".join(f"{p.id}  {p.state}  {p.command}" for p in _processes.values())
        or "no managed processes"
    )


def reap():
    if len(_processes) > MAX_PROCESSES * 2:
        exited = sorted(
            (p for p in _processes.values() if not p.running), key=lambda p: p.started
        )
        for item in exited[: len(_processes) - MAX_PROCESSES * 2]:
            _processes.pop(item.id, None)


async def stop_all():
    await asyncio.gather(*(stop(p.id) for p in list(_processes.values()) if p.running))


def running() -> list[tuple[str, str]]:
    reap()
    return [
        (f"{p.id}  {p.command}", p.id)
        for p in _processes.values()
        if p.running and p.background
    ]


def pending(cwd: Path, owner: str = "") -> list[ManagedProcess]:
    return [
        p
        for p in _processes.values()
        if (owner or p.cwd == cwd or cwd in p.cwd.parents)
        and p.owner == owner
        and p.background
        and not p.service
        and not p.notified
    ]


def _get(process_id):
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
    return f"{shlex.quote(executable)} -q -c {shlex.quote(command)} /dev/null"
