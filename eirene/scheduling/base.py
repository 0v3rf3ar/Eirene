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
TASK_SCHEMA = 3

# What an unattended run may touch. "read" is always granted.
TOOL_GROUPS = ("read", "edit", "commands", "web", "mcp", "agents")
TOOL_GROUP_HELP = {
    "read": "read and search files",
    "edit": "create and change files",
    "commands": "run shell commands and processes",
    "web": "web search, fetch, HTTP and browser",
    "mcp": "tools from enabled MCP servers",
    "agents": "delegate work to specialist agents",
}
ACCESS_LEVELS = ("sandboxed", "full-access")
WORKSPACES = ("project", "worktree")
SIGNED_OUT_LOGONS = ("s4u", "password")
# Extra seconds the OS scheduler allows beyond the run budget (setup, cleanup).
BUDGET_MARGIN = 300


@dataclass
class Schedule:
    """When a task runs."""

    kind: str = "daily"
    minutes: int = 60
    hour: int = 9
    minute: int = 0
    weekday: int = 0

    def last_due(self, now: float, created: float) -> float | None:
        """Latest moment at or before now the schedule should have fired (local time)."""
        import datetime as dt
        if self.kind == "boot" or now <= created:
            return None
        if self.kind == "interval":
            step = self.minutes * 60
            due = created + ((now - created) // step) * step
            return due if due > created else None
        moment = dt.datetime.fromtimestamp(now)
        if self.kind == "hourly":
            due = moment.replace(minute=0, second=0, microsecond=0)
        else:
            due = moment.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
            if self.kind == "weekly":
                due -= dt.timedelta(days=(due.weekday() - self.weekday) % 7)
            if due > moment:
                due -= dt.timedelta(days=7 if self.kind == "weekly" else 1)
        stamp = due.timestamp()
        return stamp if stamp >= created else None

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
    access: str = "sandboxed"
    tools: list[str] = field(default_factory=lambda: list(TOOL_GROUPS))
    # MCP servers whose tools the run may call without a person to approve them;
    # ["*"] means every server enabled in /mcp at run time.
    mcp_servers: list[str] = field(default_factory=list)
    # Skills the run may load; None follows the saved skill settings.
    skills: list[str] | None = None
    workspace: str = "project"
    # Windows only: keep running while signed out, via S4U (no password, needs an
    # elevated install) or the account's password (kept by Windows, not Eirene).
    run_signed_out: bool = False
    signed_out_logon: str = ""

    @property
    def unit(self) -> str:
        return f"eirene-{self.id}"

    @property
    def budget(self) -> int:
        """Longest a whole invocation can take: every attempt plus the waits between."""
        return (self.retries + 1) * self.timeout + self.retries * self.retry_delay

    def describe_access(self) -> str:
        plain = [group for group in self.tools if group != "mcp"]
        tools = "all tools" if set(plain) >= set(TOOL_GROUPS) - {"mcp"} else (
            "read only" if set(plain) <= {"read"} else ", ".join(plain))
        place = "git copy" if self.workspace == "worktree" else "in place"
        extra = f" · MCP: {self.describe_mcp()}" if self.mcp_servers else ""
        return f"{self.access} · {tools}{extra} · {place}"

    def describe_mcp(self) -> str:
        return describe_names(self.mcp_servers, every="every enabled server")

    def describe_skills(self) -> str:
        return "saved skill settings" if self.skills is None else describe_names(self.skills)

    def describe_model(self) -> str:
        if not self.provider:
            return "the active provider and model at run time"
        return f"{self.provider} / {self.model or 'its saved model'}"

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
                    env=_task_env(data.get("env")),
                    access=(data.get("access") if data.get("access") in ACCESS_LEVELS
                            else "sandboxed"),
                    tools=_task_tools(data.get("tools")),
                    mcp_servers=_names(data.get("mcp_servers")) or [],
                    skills=_names(data.get("skills")),
                    workspace=(data.get("workspace") if data.get("workspace") in WORKSPACES
                               else "project"),
                    run_signed_out=bool(data.get("run_signed_out", False)),
                    signed_out_logon=(data.get("signed_out_logon")
                                      if data.get("signed_out_logon") in SIGNED_OUT_LOGONS
                                      else ""))


def _task_tools(raw) -> list[str]:
    # Records written before tool groups existed ran with every tool.
    if not isinstance(raw, list):
        return list(TOOL_GROUPS)
    chosen = {str(item) for item in raw} | {"read"}
    return [group for group in TOOL_GROUPS if group in chosen]


def parse_tools(text: str) -> list[str]:
    """Read a tool list such as 'edit, commands' or 'all'."""
    raw = (text or "").strip().lower()
    if raw in ("all", "everything", "*"):
        return list(TOOL_GROUPS)
    if raw in ("", "read", "read only", "read-only", "readonly", "none"):
        return ["read"]
    aliases = {"write": "edit", "edits": "edit", "files": "edit", "shell": "commands",
               "command": "commands", "exec": "commands", "network": "web",
               "internet": "web", "agent": "agents", "subagents": "agents"}
    chosen = {"read"}
    for token in re.split(r"[\s,+]+", raw):
        if not token:
            continue
        token = aliases.get(token, token)
        if token not in TOOL_GROUPS:
            raise SchedulerError(f"unknown tool group '{token}'; use "
                                 + ", ".join(TOOL_GROUPS) + " or 'all'")
        chosen.add(token)
    return [group for group in TOOL_GROUPS if group in chosen]


def _names(raw) -> list[str] | None:
    if not isinstance(raw, list):
        return None
    seen: list[str] = []
    for item in raw:
        name = str(item).strip()
        if name and name not in seen:
            seen.append(name)
    return seen


def parse_names(text: str) -> list[str]:
    """Read 'a, b c', 'all' (["*"]) or 'none' ([]) for MCP servers or skills."""
    raw = (text or "").strip()
    if raw.lower() in ("all", "every", "*"):
        return ["*"]
    if raw.lower() in ("", "none"):
        return []
    return _names(re.split(r"[\s,]+", raw)) or []


def describe_names(names: list[str], *, every: str = "all") -> str:
    if names == ["*"]:
        return every
    return ", ".join(names) if names else "none"


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
    # Whether install() can honour Task.run_signed_out.
    supports_signed_out = False

    def install(self, task: Task, password: str | None = None) -> str:
        raise NotImplementedError

    def remove(self, task: Task) -> str:
        raise NotImplementedError

    def status(self, task: Task) -> str:
        return "unknown"

    def set_enabled(self, task: Task, enabled: bool) -> str:
        """Pause or resume the installed entry without removing it."""
        raise SchedulerError(f"{self.name or 'this scheduler'} cannot pause a routine")

    def run_now(self, task: Task) -> str:
        """Ask the scheduler to start the routine once, now, outside its schedule."""
        raise SchedulerError(f"{self.name or 'this scheduler'} cannot start a routine")

    def warnings(self, task: "Task | None" = None) -> list[str]:
        return []

    def validate(self, schedule: Schedule) -> None:
        """Raise when this scheduler cannot express the schedule."""

    def signed_out_mode(self) -> tuple[str, str]:
        """("s4u" | "password", "") when signed-out runs are possible, else ("", why)."""
        return "", "not supported by this scheduler"

    def verify_password(self, password: str) -> str:
        """Empty when the password lets Windows start a signed-out run, else why not."""
        return "not supported by this scheduler"

    def password_changed_at(self) -> float | None:
        """When the account password last changed, where the platform can tell."""
        return None


class UnsupportedBackend(Backend):
    """Fallback for unknown platforms."""

    name = "none"
    available = False

    def install(self, task: Task, password: str | None = None) -> str:
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
    # Not resolve(): a venv's python is a symlink to the base interpreter, and
    # following it drops the venv, so the scheduled run cannot import eirene.
    return [os.path.abspath(sys.executable), "-m", "eirene", "--task", task.id]


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
    tasks = load_tasks()
    # An exact id wins; names are not unique, so only an unambiguous name matches.
    by_id = next((task for task in tasks if task.id == task_id), None)
    if by_id:
        return by_id
    named = [task for task in tasks if task.name == task_id]
    return named[0] if len(named) == 1 else None
