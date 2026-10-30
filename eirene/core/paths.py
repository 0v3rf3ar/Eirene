"""Fixed on-disk locations."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path

ENV_HOME = "EIRENE_HOME"
# Child Eirene processes inherit a session TMPDIR; keep nesting under the real one.
_SYSTEM_TEMP = os.environ.get("EIRENE_SYSTEM_TEMP") or tempfile.gettempdir()
_session_temp: Path | None = None


def home() -> Path:
    """Root data dir, overridable for tests."""
    override = os.environ.get(ENV_HOME)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".local" / "share" / "eirene"


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
    root = home()
    legacy = Path.home() / ".local" / "eirene"
    if not os.environ.get(ENV_HOME) and not root.exists() and legacy.is_dir():
        root.parent.mkdir(parents=True, exist_ok=True)
        legacy.rename(root)
    for path in (home(), sessions_dir(), skills_dir(), logs_dir(),
                 projects_dir(), plugins_dir(), plans_dir(), task_runs_dir(),
                 task_locks_dir()):
        path.mkdir(parents=True, exist_ok=True)
    _tighten(home())


def temp_root() -> Path:
    """Eirene's private folder in the OS temp directory, e.g. /tmp/eirene-1000."""
    name = f"eirene-{os.getuid()}" if hasattr(os, "getuid") else "eirene"
    return _private(Path(_SYSTEM_TEMP) / name)


def temp_dir() -> Path:
    """The active session's temp folder, or the shared root before one starts."""
    return _session_temp or temp_root()


def use_session_temp(workspace: Path, session_id: str) -> Path:
    """Send every temp file of Eirene and its commands to this session's folder."""
    global _session_temp
    name = re.sub(r"[^A-Za-z0-9]", "-", str(workspace))
    if len(name) > 64:
        # Deep workspaces would push Windows paths past MAX_PATH; keep the tail readable.
        name = name[-48:].lstrip("-") + "-" + hashlib.sha256(str(workspace).encode()).hexdigest()[:12]
    folder = _private(temp_root() / name)
    _session_temp = _private(folder / session_id)
    os.environ["EIRENE_SYSTEM_TEMP"] = _SYSTEM_TEMP
    for key in ("TMPDIR", "TEMP", "TMP"):
        os.environ[key] = str(_session_temp)
    tempfile.tempdir = str(_session_temp)
    return _session_temp


def _private(path: Path) -> Path:
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or (hasattr(os, "getuid") and path.stat().st_uid != os.getuid()):
        raise OSError(f"unsafe temporary directory: {path}")
    _tighten(path)
    return path.resolve()


def _tighten(path: Path) -> None:
    """Best-effort private permissions."""
    if os.name == "nt":
        return
    try:
        path.chmod(0o700)
    except OSError:
        pass
