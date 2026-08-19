"""macOS LaunchAgents."""

from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path

from ..core import paths
from ..core.errors import SchedulerError
from .base import Backend, Task, runner_command

AGENT_DIR = Path.home() / "Library" / "LaunchAgents"
PREFIX = "com.eirene"


class LaunchdBackend(Backend):
    """Writes and loads LaunchAgent plists."""

    name = "launchd"

    def install(self, task: Task) -> str:
        AGENT_DIR.mkdir(parents=True, exist_ok=True)
        path = plist_path(task)
        try:
            path.write_bytes(plistlib.dumps(plist_body(task)))
        except (OSError, TypeError, ValueError) as exc:
            raise SchedulerError(f"cannot write {path.name}: {exc}") from exc
        target = f"gui/{os.getuid()}"
        _run(["launchctl", "bootout", target, str(path)], check=False)
        _run(["launchctl", "bootstrap", target, str(path)])
        return f"installed {path.name}"

    def remove(self, task: Task) -> str:
        path = plist_path(task)
        _run(["launchctl", "bootout", f"gui/{os.getuid()}", str(path)], check=False)
        try:
            path.unlink()
        except FileNotFoundError:
            return "nothing to remove"
        except OSError as exc:
            raise SchedulerError(f"cannot remove {path.name}: {exc}") from exc
        return f"removed {path.name}"

    def status(self, task: Task) -> str:
        result = _run(["launchctl", "print", f"gui/{os.getuid()}/{label(task)}"],
                      check=False)
        if result.returncode != 0:
            return "not loaded"
        for line in (result.stdout or "").splitlines():
            stripped = line.strip()
            if stripped.startswith("state ="):
                return stripped.split("=", 1)[1].strip()
        return "loaded"


def label(task: Task) -> str:
    return f"{PREFIX}.{task.id}"


def plist_path(task: Task) -> Path:
    return AGENT_DIR / f"{label(task)}.plist"


def plist_body(task: Task) -> dict:
    """Build the LaunchAgent dictionary."""
    logs = paths.logs_dir()
    body: dict = {
        "Label": label(task),
        "ProgramArguments": runner_command(task),
        "WorkingDirectory": task.cwd,
        "RunAtLoad": task.schedule.kind == "boot",
        "StandardOutPath": str(logs / f"{task.unit}.log"),
        "StandardErrorPath": str(logs / f"{task.unit}.log"),
        "ProcessType": "Background",
    }
    schedule = task.schedule
    if schedule.kind == "interval":
        body["StartInterval"] = schedule.minutes * 60
    elif schedule.kind == "hourly":
        body["StartCalendarInterval"] = {"Minute": 0}
    elif schedule.kind == "weekly":
        # launchd uses 1=Sunday, 2=Monday, ..., 7=Saturday while Eirene uses
        # Python's 0=Monday, ..., 6=Sunday convention.
        body["StartCalendarInterval"] = {"Weekday": ((schedule.weekday + 1) % 7) + 1,
                                         "Hour": schedule.hour,
                                         "Minute": schedule.minute}
    elif schedule.kind == "daily":
        body["StartCalendarInterval"] = {"Hour": schedule.hour,
                                         "Minute": schedule.minute}
    return body


def _run(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise SchedulerError(f"{argv[0]} not found on this system") from exc
    except subprocess.TimeoutExpired as exc:
        raise SchedulerError(f"{argv[0]} timed out") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        raise SchedulerError(f"launchctl failed: {detail}")
    return result
