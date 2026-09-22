"""Cross-platform command execution that always terminates."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import signal
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..core.errors import ToolError
from . import activity

IS_WINDOWS = os.name == "nt"
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 3600
DEFAULT_MAX_BYTES = 200_000
DEFAULT_STALL = 60

# Commands that never exit on their own.
BLOCKED: dict[str, str] = {
    "top": "runs forever; use 'ps aux' or 'top -b -n 1'",
    "htop": "interactive; use 'ps aux'",
    "btop": "interactive; use 'ps aux'",
    "less": "pager waits for input; pipe to 'cat' or use 'head'",
    "more": "pager waits for input; use 'head'",
    "vi": "interactive editor; edit files with the file tools",
    "vim": "interactive editor; edit files with the file tools",
    "nvim": "interactive editor; edit files with the file tools",
    "nano": "interactive editor; edit files with the file tools",
    "emacs": "interactive editor; edit files with the file tools",
    "watch": "repeats forever; run the inner command once",
    "tmux": "starts a persistent session",
    "screen": "starts a persistent session",
    "man": "pager waits for input; use '--help'",
    "telnet": "interactive session",
    "ftp": "interactive session",
    "mysql": "interactive shell; pass -e 'QUERY'",
    "psql": "interactive shell; pass -c 'QUERY'",
    "sqlite3": "interactive shell; pass the SQL as an argument",
    "irb": "interactive shell",
    "node": "bare 'node' opens a REPL; pass a script",
    "python": "bare 'python' opens a REPL; pass a script or -c",
    "python3": "bare 'python3' opens a REPL; pass a script or -c",
    "ipython": "interactive shell",
    "bash": "bare 'bash' opens a shell; pass -c 'command'",
    "sh": "bare 'sh' opens a shell; pass -c 'command'",
    "zsh": "bare 'zsh' opens a shell; pass -c 'command'",
    "fish": "bare 'fish' opens a shell; pass -c 'command'",
    "pwsh": "bare 'pwsh' opens a shell; pass -Command",
    "powershell": "bare 'powershell' opens a shell; pass -Command",
    "gdb": "interactive debugger; pass -batch",
    "pdb": "interactive debugger",
}

# Commands needing a flag to be non-interactive.
CONDITIONAL: dict[str, tuple[Callable[[list[str]], bool], str]] = {
    "ping": (lambda a: any(x == "-c" or x.startswith("-n") for x in a),
             "add '-c 4' (or '-n 4' on Windows) so it stops"),
    "sudo": (lambda a: "-n" in a, "add '-n'; it cannot prompt for a password here"),
    "ssh": (lambda a: any("BatchMode=yes" in x for x in a),
            "add '-o BatchMode=yes'; it cannot answer prompts"),
    "tail": (lambda a: not any(x == "-f" or x == "-F" or x.startswith("--follow") for x in a),
             "'-f' follows forever; drop it"),
    "journalctl": (lambda a: not any(x in ("-f", "--follow") for x in a),
                   "'-f' follows forever; use '-n 200' instead"),
    "docker": (lambda a: not (a[:1] == ["attach"] or (a[:1] == ["logs"] and "-f" in a)),
               "that form follows forever; drop '-f' or use 'logs --tail'"),
    "kubectl": (lambda a: not (a[:1] == ["logs"] and ("-f" in a or "--follow" in a)),
                "'-f' follows forever; use '--tail'"),
}

SPLIT_OPS = re.compile(r"\|\||&&|[|;&]")

# Read-only commands that change nothing, so they need no approval.
SAFE: dict[str, Callable[[list[str]], bool] | None] = {
    # posix
    "ls": None, "cat": None, "pwd": None, "cd": None, "echo": None,
    "head": None, "wc": None, "stat": None, "file": None, "du": None,
    "df": None, "date": None, "whoami": None, "id": None, "uname": None,
    "hostname": None, "which": None, "whereis": None, "type": None,
    "tree": None, "basename": None, "dirname": None, "realpath": None,
    "readlink": None, "diff": None, "cmp": None, "sort": None, "uniq": None,
    "cut": None, "column": None, "nl": None, "rev": None, "seq": None,
    "printf": None, "env": None, "printenv": None, "locale": None,
    "ps": None, "free": None, "uptime": None, "lscpu": None, "lsblk": None,
    "groups": None, "users": None, "w": None, "who": None, "arch": None,
    "grep": None, "egrep": None, "fgrep": None, "rg": None, "ag": None,
    "ack": None,
    "tail": lambda args: not any(a in ("-f", "-F") or a.startswith("--follow")
                                 for a in args),
    "find": lambda args: not any(a in ("-delete", "-exec", "-execdir", "-ok",
                                       "-okdir", "-fprint", "-fls") for a in args),
    "ping": lambda args: any(a == "-c" or a.startswith("-n") for a in args),
    "git": lambda args: bool(args) and args[0] in (
        "status", "log", "diff", "show", "branch", "remote", "describe",
        "rev-parse", "ls-files", "blame", "shortlog", "tag", "config"),
    "docker": lambda args: bool(args) and args[0] in ("ps", "images", "version"),
    "kubectl": lambda args: bool(args) and args[0] in ("get", "describe", "version"),
    "systemctl": lambda args: bool(args) and args[0] in (
        "status", "list-units", "list-timers", "is-active", "is-enabled", "cat"),
    "journalctl": lambda args: not any(a in ("-f", "--follow") for a in args),
    # windows
    "dir": None, "where": None, "ver": None, "vol": None, "tasklist": None,
    "systeminfo": None, "findstr": None, "chcp": None, "getmac": None,
    "driverquery": None, "netstat": None,
    "ipconfig": lambda args: not any(a.lower() in ("/release", "/renew",
                                                   "/flushdns") for a in args),
}

# Shell syntax that could write or run something else.
UNSAFE_SYNTAX = (">", "$(", "`", "${", "\n")


def is_safe(command: str) -> bool:
    """True when a command only reads."""
    text = (command or "").strip()
    if not text or len(text) > 2000:
        return False
    if any(token in text for token in UNSAFE_SYNTAX):
        return False
    if screen(text):
        return False
    segments = SPLIT_OPS.split(text)
    return bool(segments) and all(_safe_segment(part) for part in segments)


def _safe_segment(segment: str) -> bool:
    tokens = _tokenize(segment)
    if not tokens:
        return False
    name = Path(tokens[0].strip("'\"")).name.lower()
    if name.endswith(".exe"):
        name = name[:-4]
    if name not in SAFE:
        return False
    # Never classify a caller-supplied executable by basename alone.
    if tokens[0] != name or name in {"env", "uniq", "date", "hostname", "chcp"}:
        return False
    if name == "sort":
        return not any(a.startswith(("-o", "--output", "--compress-program"))
                       or (a.startswith("-") and not a.startswith("--") and "o" in a)
                       for a in tokens[1:])
    if name == "git":
        args = tokens[1:]
        return bool(args) and args[0] in {"status", "log", "diff", "show", "describe",
                                         "rev-parse", "ls-files", "blame", "shortlog"} and not any(
            a.startswith(("--output", "--ext-diff", "--textconv")) for a in args)
    if name == "find" and any(a.startswith(("-fprint", "-fprintf", "-fls")) for a in tokens[1:]):
        return False
    check = SAFE[name]
    if check is None:
        return True
    try:
        return bool(check(tokens[1:]))
    except (IndexError, TypeError):
        return False

NONINTERACTIVE_ENV = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
    "PAGER": "cat",
    "LESS": "-FRX",
    "PIP_NO_INPUT": "1",
    "PYTHONUNBUFFERED": "1",
    "DEBIAN_FRONTEND": "noninteractive",
    "CI": "1",
    "TERM": "dumb",
    "NPM_CONFIG_YES": "true",
    "COMPOSER_NO_INTERACTION": "1",
}


@dataclass
class ShellResult:
    """Outcome of one command."""

    command: str
    exit_code: int | None
    output: str
    duration: float
    timed_out: bool = False
    truncated: bool = False
    refused: str = ""
    stalled: bool = False

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.refused

    def summary(self) -> str:
        if self.refused:
            return f"refused: {self.refused}"
        if self.stalled:
            return (f"stuck: no output for {self.duration:.0f}s, so it was killed\n"
                    f"{self.output}".rstrip())
        if self.timed_out:
            return (f"timed out after {self.duration:.0f}s and was killed\n"
                    f"{self.output}".rstrip())
        head = self.output.rstrip()
        if self.exit_code == 0:
            return head or "(no output)"
        return f"exit {self.exit_code}\n{head}".rstrip()


@dataclass
class ActiveCommand:
    """A foreground command that has not finished yet."""

    id: str
    command: str
    cwd: Path
    task: asyncio.Task | None
    process: asyncio.subprocess.Process | None = None


_active: dict[str, ActiveCommand] = {}


def active() -> list[tuple[str, str]]:
    """Return stable labels and IDs for foreground commands."""
    return [(f"{item.id}  {item.command}", item.id) for item in _active.values()]


async def stop_active(command_id: str) -> str:
    """Stop a currently executing foreground command."""
    item = _active.get(command_id.strip())
    if item is None:
        raise ToolError(f"no running command '{command_id}'")
    for _ in range(100):
        if item.process is not None or command_id not in _active:
            break
        await asyncio.sleep(0)
    if item.process is not None and item.process.returncode is None:
        await _kill_tree(item.process)
    elif item.task is not None and not item.task.done():
        item.task.cancel()
    return f"stopped {item.id}"


def screen(command: str, *, persistent: bool = False) -> str:
    """Return a refusal reason, or empty."""
    text = command.strip()
    if not text:
        return "empty command"
    for segment in SPLIT_OPS.split(text):
        reason = _screen_segment(segment, persistent=persistent)
        if reason:
            return reason
    return ""


def _screen_segment(segment: str, *, persistent: bool = False) -> str:
    tokens = _tokenize(segment)
    while tokens and ("=" in tokens[0] and not tokens[0].startswith("-")):
        tokens = tokens[1:]
    while tokens and tokens[0] in ("env", "command", "exec", "nohup", "time", "nice"):
        tokens = tokens[1:]
    if not tokens:
        return ""
    name = Path(tokens[0].strip("'\"")).name.lower()
    if IS_WINDOWS and name.endswith(".exe"):
        name = name[:-4]
    args = tokens[1:]
    if name in BLOCKED:
        if persistent and name in ("watch", "tail", "top", "htop", "btop"):
            return ""
        if name in ("python", "python3", "node", "sh", "bash", "zsh",
                    "fish", "pwsh", "powershell") and args:
            return ""
        return f"'{name}' {BLOCKED[name]}"
    if name in CONDITIONAL:
        if persistent and name in ("tail", "journalctl"):
            return ""
        predicate, hint = CONDITIONAL[name]
        try:
            if not predicate(args):
                return f"'{name}' {hint}"
        except (IndexError, TypeError):
            return ""
    return ""


def _tokenize(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=not IS_WINDOWS)
    except ValueError:
        return segment.split()


def _child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    env.update(NONINTERACTIVE_ENV)
    env.pop("EIRENE_HOME", None)
    if extra:
        env.update({str(k): str(v) for k, v in extra.items()})
    return env


def _spawn_kwargs() -> dict:
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


async def _kill_tree(process: asyncio.subprocess.Process) -> None:
    await _terminate_tree(process)

async def _terminate_tree(process: asyncio.subprocess.Process) -> None:
    """Kill the process and its children."""
    if process.returncode is not None:
        return
    if IS_WINDOWS:
        try:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(process.pid),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            await asyncio.wait_for(killer.wait(), timeout=10)
        except (OSError, asyncio.TimeoutError):
            pass
    else:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            if process.returncode is not None:
                return
            try:
                os.killpg(os.getpgid(process.pid), sig)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                return
            try:
                await asyncio.wait_for(process.wait(), timeout=3)
                return
            except asyncio.TimeoutError:
                continue
    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        pass


def _clamp_timeout(value: float | None) -> float:
    if not value or value <= 0:
        return DEFAULT_TIMEOUT
    return min(float(value), MAX_TIMEOUT)


def _clamp_stall(value: float | None, limit: float) -> float:
    """Silence allowed before we call it stuck."""
    if value is None or value <= 0:
        return 0.0
    return min(float(value), limit)


class _Capture:
    """Bounded output buffer keeping head and tail."""

    def __init__(self, limit: int):
        self.limit = max(limit, 4_000)
        self.head = bytearray()
        self.tail = bytearray()
        self.total = 0

    def feed(self, chunk: bytes) -> None:
        self.total += len(chunk)
        room = self.limit // 2 - len(self.head)
        if room > 0:
            take = chunk[:room]
            self.head += take
            chunk = chunk[len(take):]
        if not chunk:
            return
        self.tail += chunk
        excess = len(self.tail) - self.limit // 2
        if excess > 0:
            del self.tail[:excess]

    @property
    def truncated(self) -> bool:
        return self.total > len(self.head) + len(self.tail)

    def text(self) -> str:
        head = self.head.decode("utf-8", "replace")
        tail = self.tail.decode("utf-8", "replace")
        if not self.truncated:
            return head + tail
        skipped = self.total - len(self.head) - len(self.tail)
        return f"{head}\n… {skipped} bytes omitted …\n{tail}"


async def run(command: str, cwd: Path, *, timeout: float | None = None,
              max_bytes: int = DEFAULT_MAX_BYTES,
              on_output: Callable[[str], None] | None = None,
              env: dict[str, str] | None = None,
              powershell: bool = False,
              allow_blocked: bool = False,
              stall: float = DEFAULT_STALL, pty: bool = False,
              isolation: str = "none", isolate_network: bool = False,
              read_paths=(), write_paths=(), read_only: bool = False) -> ShellResult:
    """Run a command, guaranteed to return."""
    loop = asyncio.get_running_loop()
    started = loop.time()
    if not allow_blocked:
        reason = screen(command)
        if reason:
            return ShellResult(command, None, "", 0.0, refused=reason)

    command_id = uuid.uuid4().hex[:10]
    item = ActiveCommand(command_id, command, cwd, asyncio.current_task())
    _active[command_id] = item
    activity.changed()
    try:
        limit = _clamp_timeout(timeout)
        try:
            actual = command
            if pty:
                if IS_WINDOWS:
                    raise ToolError("PTY mode is not available on Windows")
                from .processes import _pty_command
                actual = _pty_command(command)
            process = await _start(actual, cwd, env, powershell,
                                   isolation=isolation,
                                   isolate_network=isolate_network, read_paths=read_paths,
                                   write_paths=write_paths, read_only=read_only)
            item.process = process
        except (OSError, ValueError) as exc:
            raise ToolError(f"cannot start command: {exc}") from exc

        capture = _Capture(max_bytes)
        timed_out = False
        stalled = False
        quiet = _clamp_stall(stall, limit)
        try:
            await asyncio.wait_for(_pump(process, capture, on_output, quiet),
                                   timeout=limit)
            await asyncio.wait_for(process.wait(), timeout=10)
        except asyncio.TimeoutError:
            timed_out = True
            stalled = quiet > 0 and loop.time() - started < limit
            await _kill_tree(process)
        except asyncio.CancelledError:
            await _kill_tree(process)
            raise
        finally:
            if process.returncode is None:
                await _kill_tree(process)

        duration = loop.time() - started
        return ShellResult(command=command, exit_code=process.returncode,
                           output=capture.text(), duration=duration,
                           timed_out=timed_out, truncated=capture.truncated,
                           stalled=stalled)
    finally:
        _active.pop(command_id, None)
        activity.changed()


async def _start(command: str, cwd: Path, env: dict[str, str] | None,
                 powershell: bool, *, stdin=subprocess.DEVNULL,
                 isolation: str = "none",
                 isolate_network: bool = False, read_paths=(), write_paths=(),
                 read_only: bool = False) -> asyncio.subprocess.Process:
    kwargs = dict(cwd=str(cwd), env=_child_env(env), stdin=stdin,
                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **_spawn_kwargs())
    if isolation != "none" or read_only:
        from . import isolation as environments
        argv = environments.command(command, cwd, backend=isolation,
                                    network=not isolate_network, read_paths=read_paths,
                                    write_paths=write_paths, read_only=read_only)
        kwargs["env"] = environments.environment({**NONINTERACTIVE_ENV, **(env or {})})
        process = await asyncio.create_subprocess_exec(*argv, **kwargs)
        return process
    if powershell and IS_WINDOWS:
        exe = "pwsh" if _has("pwsh") else "powershell"
        return await asyncio.create_subprocess_exec(
            exe, "-NoProfile", "-NonInteractive", "-Command", command, **kwargs)
    if IS_WINDOWS:
        return await asyncio.create_subprocess_exec("cmd", "/d", "/c", command, **kwargs)
    return await asyncio.create_subprocess_exec("/bin/sh", "-c", command, **kwargs)


def _has(name: str) -> bool:
    from shutil import which
    return which(name) is not None


async def _pump(process: asyncio.subprocess.Process, capture: _Capture,
                on_output: Callable[[str], None] | None,
                stall: float = 0.0) -> None:
    """Drain stdout until the process ends."""
    stream = process.stdout
    if stream is None:
        await process.wait()
        return
    while True:
        if stall <= 0:
            chunk = await stream.read(8192)
        else:
            chunk = await asyncio.wait_for(stream.read(8192), timeout=stall)
        if not chunk:
            break
        capture.feed(chunk)
        if on_output:
            try:
                on_output(chunk.decode("utf-8", "replace"))
            except Exception:
                pass
    await process.wait()
