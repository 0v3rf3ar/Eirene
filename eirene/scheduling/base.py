"""Task records and schedule parsing."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ..core import paths
from ..core.errors import SchedulerError

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
TASK_SCHEMA = 2


@dataclass
class Schedule:
    """When a task runs."""

    kind: str = "daily"
    minutes: int = 60
    hour: int = 9
    minute: int = 0
    weekday: int = 0

    def describe(self) -> str:
        if self.kind == "interval":
            if self.minutes % 60 == 0 and self.minutes >= 60:
                return f"every {self.minutes // 60}h"
            return f"every {self.minutes}m"
        if self.kind == "hourly":
            return "hourly"
        if self.kind == "boot":
            return "at startup"
        clock = f"{self.hour:02d}:{self.minute:02d}"
        if self.kind == "weekly":
            return f"every {WEEKDAYS[self.weekday]} at {clock}"
        return f"daily at {clock}"


@dataclass
class Task:
    """One scheduled agent run."""

    id: str
    name: str
    prompt: str
    cwd: str
    schedule: Schedule
    provider: str = ""
    model: str = ""
    created: float = field(default_factory=time.time)
    enabled: bool = True
    retries: int = 0
    retry_delay: int = 30
    timeout: int = 3600
    allow_overlap: bool = False
    timezone: str = "local"
    env: dict[str, str] = field(default_factory=dict)

    @property
    def unit(self) -> str:
        return f"eirene-{self.id}"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schedule"] = asdict(self.schedule)
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "Task":
        raw = data.get("schedule") or {}
        return Task(id=str(data.get("id", "")), name=str(data.get("name", "")),
                    prompt=str(data.get("prompt", "")), cwd=str(data.get("cwd", "")),
                    schedule=Schedule(**{k: raw[k] for k in
                                         ("kind", "minutes", "hour", "minute", "weekday")
                                         if k in raw}),
                    provider=str(data.get("provider", "")),
                    model=str(data.get("model", "")),
                    created=float(data.get("created", 0) or 0),
                    enabled=bool(data.get("enabled", True)),
                    retries=max(0, min(int(data.get("retries", 0) or 0), 10)),
                    retry_delay=max(0, min(int(data.get("retry_delay", 30) or 30), 3600)),
                    timeout=max(60, min(int(data.get("timeout", 3600) or 3600), 86400)),
                    allow_overlap=bool(data.get("allow_overlap", False)),
                    timezone=str(data.get("timezone", "local") or "local"),
                    env=_task_env(data.get("env")))


def _task_env(raw) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    blocked = {"EIRENE_HOME", "PYTHONPATH", "PYTHONHOME", "LD_PRELOAD"}
    return {str(key): str(value) for key, value in raw.items()
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(key))
            and str(key) not in blocked and len(str(value)) <= 10_000}


class Backend:
    """Platform scheduler interface."""

    name = ""
    available = True

    def install(self, task: Task) -> str:
        raise NotImplementedError

    def remove(self, task: Task) -> str:
        raise NotImplementedError

    def status(self, task: Task) -> str:
        return "unknown"

    def warnings(self) -> list[str]:
        return []


class UnsupportedBackend(Backend):
    """Fallback for unknown platforms."""

    name = "none"
    available = False

    def install(self, task: Task) -> str:
        raise SchedulerError(f"scheduling is not supported on {sys.platform}")

    def remove(self, task: Task) -> str:
        raise SchedulerError(f"scheduling is not supported on {sys.platform}")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def parse_schedule(text: str) -> Schedule:
    """Read a friendly schedule expression."""
    raw = (text or "").strip().lower()
    if not raw:
        raise SchedulerError("no schedule given")
    if raw in ("boot", "startup", "at boot", "at startup", "login"):
        return Schedule(kind="boot")
    if raw == "hourly":
        return Schedule(kind="hourly")

    match = re.fullmatch(r"every\s+(\d+)\s*(m|min|mins|minutes?|h|hr|hrs|hours?)", raw)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        minutes = value * 60 if unit.startswith("h") else value
        if minutes < 1:
            raise SchedulerError("interval must be at least 1 minute")
        if minutes > 60 * 24 * 30:
            raise SchedulerError("interval is too long; use a daily schedule")
        return Schedule(kind="interval", minutes=minutes)

    match = re.fullmatch(r"(?:every\s+)?(\w{3,9})(?:day)?\s+at\s+(\d{1,2}):(\d{2})", raw)
    if match and _weekday(match.group(1)) is not None:
        hour, minute = _clock(match.group(2), match.group(3))
        return Schedule(kind="weekly", hour=hour, minute=minute,
                        weekday=_weekday(match.group(1)))

    match = re.fullmatch(r"(?:daily\s+)?at\s+(\d{1,2}):(\d{2})", raw)
    if not match:
        match = re.fullmatch(r"daily\s+(\d{1,2}):(\d{2})", raw)
    if match:
        hour, minute = _clock(match.group(1), match.group(2))
        return Schedule(kind="daily", hour=hour, minute=minute)

    if raw == "daily":
        return Schedule(kind="daily", hour=9, minute=0)

    raise SchedulerError("could not read that schedule; try 'every 30m', 'hourly', "
                         "'daily at 09:00', 'mon at 18:30' or 'at startup'")


def _weekday(token: str) -> int | None:
    text = token[:3]
    return WEEKDAYS.index(text) if text in WEEKDAYS else None


def _clock(hour_text: str, minute_text: str) -> tuple[int, int]:
    hour, minute = int(hour_text), int(minute_text)
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise SchedulerError("time must be between 00:00 and 23:59")
    return hour, minute


def runner_command(task: Task) -> list[str]:
    """Argv that runs one task headlessly."""
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve()), "--task", task.id]
    return [str(Path(sys.executable).resolve()), "-m", "eirene", "--task", task.id]


def quoted_command(task: Task) -> str:
    argv = runner_command(task)
    if os.name == "nt":
        return subprocess.list2cmdline(argv)
    return " ".join(shlex.quote(part) for part in argv)


def load_tasks() -> list[Task]:
    """Read tasks.json, tolerating damage."""
    path = paths.tasks_file()
    if not path.exists():
        return []
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if isinstance(body, dict):
        body = body.get("tasks", [])
    if not isinstance(body, list):
        return []
    tasks = []
    for item in body:
        if not isinstance(item, dict):
            continue
        try:
            task = Task.from_dict(item)
        except (TypeError, ValueError):
            continue
        if task.id:
            tasks.append(task)
    return tasks


def save_tasks(tasks: list[Task]) -> None:
    """Write tasks.json atomically."""
    path = paths.tasks_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"version": TASK_SCHEMA,
                          "tasks": [task.to_dict() for task in tasks]}, indent=2)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise SchedulerError(f"cannot save tasks: {exc}") from exc


def find_task(task_id: str) -> Task | None:
    for task in load_tasks():
        if task.id == task_id or task.name == task_id:
            return task
    return None
