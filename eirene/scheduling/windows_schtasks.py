"""Windows Task Scheduler."""

from __future__ import annotations

import subprocess

from ..core.errors import SchedulerError
from .base import Backend, Task, quoted_command

DAY_CODES = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}


class SchtasksBackend(Backend):
    """Drives schtasks.exe."""

    name = "schtasks"

    def install(self, task: Task) -> str:
        _run(create_argv(task))
        return f"installed task {task_name(task)}"

    def remove(self, task: Task) -> str:
        result = _run(["schtasks", "/Delete", "/TN", task_name(task), "/F"], check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[:200]
            if "cannot find" in detail.lower():
                return "nothing to remove"
            raise SchedulerError(f"schtasks failed: {detail}")
        return f"removed task {task_name(task)}"

    def status(self, task: Task) -> str:
        result = _run(["schtasks", "/Query", "/TN", task_name(task), "/FO", "LIST"],
                      check=False)
        if result.returncode != 0:
            return "not installed"
        for line in (result.stdout or "").splitlines():
            if line.lower().startswith("status:"):
                return line.split(":", 1)[1].strip().lower()
        return "installed"


def task_name(task: Task) -> str:
    return f"Eirene-{task.id}"


def create_argv(task: Task) -> list[str]:
    """Build the schtasks /Create command."""
    schedule = task.schedule
    argv = ["schtasks", "/Create", "/TN", task_name(task),
            "/TR", quoted_command(task), "/F", "/RL", "LIMITED"]
    clock = f"{schedule.hour:02d}:{schedule.minute:02d}"
    if schedule.kind == "interval":
        argv += ["/SC", "MINUTE", "/MO", str(schedule.minutes)]
    elif schedule.kind == "hourly":
        argv += ["/SC", "HOURLY"]
    elif schedule.kind == "boot":
        argv += ["/SC", "ONLOGON"]
    elif schedule.kind == "weekly":
        argv += ["/SC", "WEEKLY", "/D", DAY_CODES[schedule.weekday], "/ST", clock]
    else:
        argv += ["/SC", "DAILY", "/ST", clock]
    return argv


def _run(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=60,
                                stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        raise SchedulerError("schtasks.exe not found") from exc
    except subprocess.TimeoutExpired as exc:
        raise SchedulerError("schtasks timed out") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        raise SchedulerError(f"schtasks failed: {detail}")
    return result
