"""Display helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path

MAX_PATH = 60
MAX_NOTICE = 400
_ESCAPES = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|[\x00-\x09\x0b-\x1f\x7f\u21b5]")


def display_path(path: Path | str, limit: int = MAX_PATH) -> str:
    """Shorten a path for display."""
    limit = max(limit, 4)
    text = str(path)
    if os.name != "nt":
        text = _tilde(text)
    if len(text) <= limit:
        return text
    shortened = _elide(text, limit)
    if len(shortened) > limit:
        shortened = "…" + shortened[-(limit - 1):]
    return shortened


def _tilde(text: str) -> str:
    """Replace the home prefix with ~."""
    try:
        home = str(Path.home())
    except (RuntimeError, OSError):
        return text
    if text == home:
        return "~"
    if home != "/" and text.startswith(home + os.sep):
        return "~" + text[len(home):]
    return text


def _elide(text: str, limit: int) -> str:
    """Keep the root and the last segments."""
    parts = text.split(os.sep)
    if len(parts) <= 2:
        return text[:limit - 1] + "…"
    head = parts[0]
    prefix = f"{head}{os.sep}…{os.sep}" if head else f"{os.sep}…{os.sep}"
    tail: list[str] = []
    length = len(prefix)
    for part in reversed(parts[1:]):
        if tail and length + len(part) + 1 > limit:
            break
        tail.insert(0, part)
        length += len(part) + 1
    return prefix + os.sep.join(tail)


def pasted_label(text: str) -> str:
    """Summarise a folded paste."""
    lines = text.count("\n") + 1
    if lines > 1:
        return f"[pasted {lines} lines]"
    return f"[pasted {len(text)} chars]"


def strip_escapes(text: str) -> str:
    """Remove what a terminal would obey: escapes, clears, carriage returns.

    A command that paints its own screen (curses, progress bars, an ASCII
    animation) otherwise wipes the interface it is being displayed in.
    """
    # Never trim: a streamed chunk may end mid-word, and the space matters.
    return _ESCAPES.sub("", str(text or ""))


def safe_notice(text: str, limit: int = MAX_NOTICE) -> str:
    """Strip anything that would corrupt the transcript, keeping line breaks."""
    body = _ESCAPES.sub(" ", str(text or ""))
    body = "\n".join(" ".join(line.split()) for line in body.split("\n"))
    if len(body) <= limit:
        return body
    return body[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
