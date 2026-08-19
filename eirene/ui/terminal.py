"""Talking to the terminal and the desktop."""

from __future__ import annotations

import base64
import os
import shutil
import subprocess

IS_WINDOWS = os.name == "nt"

# Clipboard helpers, best first.
WRITERS: list[tuple[str, list[str]]] = [
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("pbcopy", ["pbcopy"]),
    ("clip.exe", ["clip.exe"]),
    ("clip", ["clip"]),
]


def clean_title(text: str) -> str:
    """Strip anything the terminal would choke on."""
    safe = "".join(char for char in str(text) if char.isprintable())
    return safe.replace("\x07", "").replace("\x1b", "")[:120]


def write_terminal_title(driver, text: str) -> bool:
    """Name the window and the tab."""
    if driver is None:
        return False
    title = clean_title(text)
    try:
        driver.write(f"\x1b]0;{title}\x07")
        flush = getattr(driver, "flush", None)
        if flush:
            flush()
    except Exception:  # noqa: BLE001
        return False
    return True


def clipboard_tool() -> list[str]:
    """The first clipboard helper on this machine."""
    for name, command in WRITERS:
        if shutil.which(name):
            return command
    return []


def copy_to_system(text: str) -> str:
    """Put text on the real clipboard; returns the tool used."""
    command = clipboard_tool()
    if not command:
        return ""
    try:
        process = subprocess.run(command, input=text.encode("utf-8"),
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return command[0] if process.returncode == 0 else ""


def osc52(text: str) -> str:
    """The escape sequence some terminals accept."""
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    return f"\x1b]52;c;{encoded}\a"
