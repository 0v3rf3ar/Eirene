"""Platform scheduling backends."""

from __future__ import annotations

import sys

from .base import Backend, Task, load_tasks, save_tasks


def backend() -> Backend:
    """Pick the backend for this OS."""
    if sys.platform.startswith("linux"):
        from .linux_systemd import SystemdBackend
        return SystemdBackend()
    if sys.platform == "darwin":
        from .macos_launchd import LaunchdBackend
        return LaunchdBackend()
    if sys.platform in ("win32", "cygwin"):
        from .windows_schtasks import SchtasksBackend
        return SchtasksBackend()
    from .base import UnsupportedBackend
    return UnsupportedBackend()


__all__ = ["Backend", "Task", "backend", "load_tasks", "save_tasks"]
