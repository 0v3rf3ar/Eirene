"""systemd user timers."""

from __future__ import annotations

from ..core.subprocesses import external_environment

import os
import subprocess
from pathlib import Path

from ..core.errors import SchedulerError
from .base import BUDGET_MARGIN, Backend, Task, WEEKDAYS, quoted_command

UNIT_DIR = Path.home() / ".config" / "systemd" / "user"


class SystemdBackend(Backend):
    """Writes .service and .timer units."""

    name = "systemd"

    def install(self, task: Task, password: str | None = None) -> str:
        UNIT_DIR.mkdir(parents=True, exist_ok=True)
        service = UNIT_DIR / f"{task.unit}.service"
        timer = UNIT_DIR / f"{task.unit}.timer"
        try:
            service.write_text(service_unit(task), encoding="utf-8")
            timer.write_text(timer_unit(task), encoding="utf-8")
        except OSError as exc:
            raise SchedulerError(f"cannot write unit files: {exc}") from exc
        _run(["systemctl", "--user", "daemon-reload"])
        _activate(task)
        return f"installed {timer.name}"

    def set_enabled(self, task: Task, enabled: bool) -> str:
        if enabled:
            _activate(task)
            return f"enabled {task.unit}.timer"
        _run(["systemctl", "--user", "disable", "--now", f"{task.unit}.timer"])
        return f"disabled {task.unit}.timer"

    def run_now(self, task: Task) -> str:
        # --no-block: a oneshot start would otherwise wait for the whole run.
        _run(["systemctl", "--user", "start", "--no-block", f"{task.unit}.service"])
        return f"started {task.unit}.service"

    def remove(self, task: Task) -> str:
        _run(["systemctl", "--user", "disable", "--now", f"{task.unit}.timer"],
             check=False)
        removed = []
        for path in (UNIT_DIR / f"{task.unit}.timer", UNIT_DIR / f"{task.unit}.service"):
            try:
                path.unlink()
                removed.append(path.name)
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise SchedulerError(f"cannot remove {path.name}: {exc}") from exc
        _run(["systemctl", "--user", "daemon-reload"], check=False)
        # A failed last run would otherwise linger in `systemctl --failed` as not-found.
        _run(["systemctl", "--user", "reset-failed", f"{task.unit}.service",
              f"{task.unit}.timer"], check=False)
        return f"removed {', '.join(removed)}" if removed else "nothing to remove"

    def status(self, task: Task) -> str:
        result = _run(["systemctl", "--user", "is-active", f"{task.unit}.timer"],
                      check=False)
        state = (result.stdout or "").strip() or "unknown"
        if state != "active":
            if task.schedule.kind == "boot":
                enabled = _run(["systemctl", "--user", "is-enabled", f"{task.unit}.timer"],
                               check=False)
                if (enabled.stdout or "").strip() == "enabled":
                    return "waits for the next startup"
            return state
        service = _run(["systemctl", "--user", "is-active", f"{task.unit}.service"],
                       check=False)
        if (service.stdout or "").strip() in ("active", "activating"):
            return "running now"
        listing = _run(["systemctl", "--user", "list-timers", "--no-pager",
                        "--no-legend", f"{task.unit}.timer"], check=False)
        fields = (listing.stdout or "").split()
        # NEXT is "-" while nothing is queued; otherwise "Tue 2026-11-03 15:53:57 +0330".
        if len(fields) >= 3 and fields[0] != "-":
            return f"active, next {' '.join(fields[:3])}"
        return "active"

    def warnings(self, task: Task | None = None) -> list[str]:
        notes = []
        user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
        result = _run(["loginctl", "show-user", user, "--property=Linger"], check=False)
        if user and "Linger=no" in (result.stdout or ""):
            notes.append(f"timers stop at logout; run 'loginctl enable-linger {user}'")
        return notes


def service_unit(task: Task) -> str:
    """Render the .service file."""
    lines = [
        "[Unit]",
        f"Description=Eirene task: {task.name}",
        "After=network-online.target",
        "",
        "[Service]",
        "Type=oneshot",
        # "-": a missing folder must not stop the start; Eirene then records the
        # failure in the routine's history instead of systemd failing silently.
        f"WorkingDirectory=-{task.cwd}",
        f"ExecStart={quoted_command(task)}",
        f"TimeoutStartSec={task.budget + BUDGET_MARGIN}",
    ]
    for key, value in task.env.items():
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'Environment="{key}={escaped}"')
    lines += [
        "",
        "[Install]",
        "WantedBy=default.target",
        "",
    ]
    return "\n".join(lines)


def timer_unit(task: Task) -> str:
    """Render the .timer file."""
    lines = ["[Unit]", f"Description=Eirene schedule: {task.name}", "", "[Timer]"]
    schedule = task.schedule
    if schedule.kind == "interval":
        # OnActiveSec counts from when the timer starts (install, enable, or each
        # login/boot). OnBootSec would already be in the past at install time, and
        # systemd fires such a timer immediately.
        lines.append(f"OnActiveSec={schedule.minutes}min")
        lines.append(f"OnUnitActiveSec={schedule.minutes}min")
    elif schedule.kind == "boot":
        lines.append("OnBootSec=2min")
    else:
        lines.append(f"OnCalendar={on_calendar(task)}")
    lines += ["Persistent=true", f"Unit={task.unit}.service", "",
              "[Install]", "WantedBy=timers.target", ""]
    return "\n".join(lines)


def on_calendar(task: Task) -> str:
    """systemd OnCalendar expression."""
    schedule = task.schedule
    if schedule.kind == "hourly":
        value = "hourly"
        return value if task.timezone == "local" else f"{value} {task.timezone}"
    clock = f"{schedule.hour:02d}:{schedule.minute:02d}:00"
    if schedule.kind == "weekly":
        value = f"{WEEKDAYS[schedule.weekday].capitalize()} *-*-* {clock}"
    else:
        value = f"*-*-* {clock}"
    return value if task.timezone == "local" else f"{value} {task.timezone}"


def _activate(task: Task) -> None:
    """Enable the timer; start it now unless that would fire it right away."""
    timer = f"{task.unit}.timer"
    if task.schedule.kind == "boot":
        # OnBootSec= in the past makes a freshly started timer elapse at once, so a
        # startup routine is only enabled: it starts with the next user session.
        _run(["systemctl", "--user", "enable", timer])
    else:
        _run(["systemctl", "--user", "enable", "--now", timer])


def _run(argv: list[str], check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                                stdin=subprocess.DEVNULL, env=external_environment())
    except FileNotFoundError as exc:
        raise SchedulerError(f"{argv[0]} not found on this system") from exc
    except subprocess.TimeoutExpired as exc:
        raise SchedulerError(f"{argv[0]} timed out") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        raise SchedulerError(f"{' '.join(argv[:3])} failed: {detail}")
    return result
