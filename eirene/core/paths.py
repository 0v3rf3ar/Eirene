"""Fixed on-disk locations."""

from __future__ import annotations

import os
from pathlib import Path

ENV_HOME = "EIRENE_HOME"


def home() -> Path:
    """Root data dir, overridable for tests."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "eirene"


def config_file() -> Path:
    return home() / "config.json"


def sessions_dir() -> Path:
    return home() / "sessions"


def skills_dir() -> Path:
    return home() / "skills"


def tasks_file() -> Path:
    return home() / "tasks.json"


def logs_dir() -> Path:
    return home() / "logs"


def runtime_log() -> Path:
    return logs_dir() / "eirene.jsonl"


def checkpoints_dir() -> Path:
    return home() / "checkpoints"


def projects_dir() -> Path:
    return home() / "projects"


def plugins_dir() -> Path:
    return home() / "plugins"


def plans_dir() -> Path:
    return home() / "plans"


def task_runs_dir() -> Path:
    return home() / "task-runs"


def task_locks_dir() -> Path:
    return home() / "task-locks"


def ensure_tree() -> None:
    """Create data dirs if missing."""
    for path in (home(), sessions_dir(), skills_dir(), logs_dir(), checkpoints_dir(),
                 projects_dir(), plugins_dir(), plans_dir(), task_runs_dir(),
                 task_locks_dir()):
        path.mkdir(parents=True, exist_ok=True)
    _tighten(home())


def _tighten(path: Path) -> None:
    """Best-effort private permissions."""
    if os.name == "nt":
        return
    try:
        path.chmod(0o700)
    except OSError:
        pass
