"""Crash reports: a durable, private record of every unexpected error.

Everything here runs while something else is already failing, so no function
in this module may raise. A report that cannot be written is logged and
skipped; it never turns one error into two.
"""

from __future__ import annotations

import itertools
import os
import platform
import sys
import time
import traceback
from pathlib import Path

from . import paths
from .logging import get as get_logger

KEEP_REPORTS = 20
SUMMARY_CHARS = 200
# Terminal facts that explain most rendering and input bugs, never their values
# when they could identify the user.
TERMINAL_ENV = ("TERM", "TERM_PROGRAM", "TERM_PROGRAM_VERSION", "COLORTERM",
                "WT_SESSION", "TMUX", "STY", "LANG", "LC_ALL")
PRESENCE_ONLY = {"WT_SESSION", "TMUX", "STY"}

_sequence = itertools.count(1)


def crash_dir() -> Path:
    return paths.logs_dir() / "crashes"


def summary(error: BaseException) -> str:
    """One display-safe line: the exception type and the start of its message."""
    message = " ".join(str(error).split())
    if len(message) > SUMMARY_CHARS:
        message = message[:SUMMARY_CHARS - 1] + "…"
    name = type(error).__name__
    return f"{name}: {message}" if message else name


def format_traceback(error: BaseException, *, limit: int | None = None) -> str:
    """The traceback without local variables, which may hold credentials."""
    lines = traceback.format_exception(type(error), error, error.__traceback__)
    text = "".join(lines)
    if limit is None:
        return text
    return "\n".join(text.rstrip().splitlines()[-limit:])


def record(error: BaseException, *, where: str, fatal: bool = False,
           context: dict[str, object] | None = None) -> Path | None:
    """Log the error and write a crash report; return its path when written."""
    logger = get_logger()
    try:
        # Before logging is configured Python's last-resort handler would print
        # to the terminal; the report file below is the record in that case.
        if logger.handlers:
            logger.error("ui.error", exc_info=(type(error), error, error.__traceback__),
                         extra={"where": where, "fatal": fatal, "error": summary(error)})
    except Exception:  # noqa: BLE001 - logging must not take the app down
        pass
    try:
        return _write(error, where=where, fatal=fatal, context=context or {})
    except Exception as exc:  # noqa: BLE001
        try:
            if logger.handlers:
                logger.warning("crash.report_failed", extra={"reason": repr(exc)})
        except Exception:  # noqa: BLE001
            pass
        return None


def recent(limit: int = KEEP_REPORTS) -> list[Path]:
    """Newest crash reports first."""
    try:
        reports = sorted(crash_dir().glob("crash-*.txt"),
                         key=lambda path: path.stat().st_mtime, reverse=True)
    except OSError:
        return []
    return reports[:limit]


def _write(error: BaseException, *, where: str, fatal: bool,
           context: dict[str, object]) -> Path:
    from .. import __version__

    directory = crash_dir()
    directory.mkdir(parents=True, exist_ok=True)
    paths._tighten(directory)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    target = directory / f"crash-{stamp}-{os.getpid()}-{next(_sequence)}.txt"
    lines = [
        "Eirene crash report",
        f"time: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        f"where: {where}",
        f"fatal: {'yes' if fatal else 'no (Eirene kept running)'}",
        f"version: {__version__}",
        f"python: {platform.python_version()} ({sys.executable})",
        f"platform: {platform.platform()}",
        f"frozen: {bool(getattr(sys, 'frozen', False))}",
        f"textual: {_textual_version()}",
    ]
    for key in TERMINAL_ENV:
        value = os.environ.get(key)
        if value is not None:
            lines.append(f"env {key}: {'set' if key in PRESENCE_ONLY else value}")
    for key, value in context.items():
        lines.append(f"{key}: {value}")
    lines += ["", format_traceback(error)]
    with target.open("x", encoding="utf-8", errors="replace") as handle:
        if os.name != "nt":
            target.chmod(0o600)
        handle.write("\n".join(lines))
    _prune()
    return target


def _prune() -> None:
    for stale in recent(limit=10_000)[KEEP_REPORTS:]:
        try:
            stale.unlink()
        except OSError:
            pass


def _textual_version() -> str:
    try:
        from importlib.metadata import version
        return version("textual")
    except Exception:  # noqa: BLE001
        return "unknown"
