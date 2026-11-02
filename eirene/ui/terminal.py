"""Talking to the terminal and the desktop."""

from __future__ import annotations

from ..core.subprocesses import external_environment

import base64
import os
import shutil
import subprocess

IS_WINDOWS = os.name == "nt"
SCREEN_CHUNK = 76

# Clipboard helpers, best first.
WRITERS: list[tuple[str, list[str]]] = [
    ("wl-copy", ["wl-copy"]),
    ("xclip", ["xclip", "-selection", "clipboard"]),
    ("xsel", ["xsel", "--clipboard", "--input"]),
    ("pbcopy", ["pbcopy"]),
    ("clip.exe", ["clip.exe"]),
    ("clip", ["clip"]),
]


def cell_mouse_driver(driver_class):
    """The platform driver, with mouse clicks always reported in whole cells.

    Terminals with in-band resize reports (kitty, Ghostty, foot...) make Textual
    switch to pixel mouse reporting and divide by the window's pixel size. Window
    padding and display scaling make those pixel units disagree, so clicks land
    on the wrong row and the banner and companion never see them. Eirene only
    needs cells, which every terminal reports the same way.
    """
    if not hasattr(driver_class, "_query_in_band_window_resize"):
        return driver_class

    class CellMouseDriver(driver_class):
        def _query_in_band_window_resize(self) -> None:
            """Keep mode 2048 off (even if a crashed app left it on); SIGWINCH reports resizes."""
            self.write("\x1b[?2048l")

        def _enable_mouse_pixels(self) -> None:
            """Keep SGR cell coordinates (no mode 1016)."""

    CellMouseDriver.__name__ = CellMouseDriver.__qualname__ = driver_class.__name__
    return CellMouseDriver


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


def remote_session(env=None) -> bool:
    """Over SSH the clipboard, browser and desktop belong to the user's own machine."""
    env = os.environ if env is None else env
    return bool(env.get("SSH_CONNECTION") or env.get("SSH_CLIENT") or env.get("SSH_TTY"))


def clipboard_tool() -> list[str]:
    """The first clipboard helper on this machine; none over SSH, where it is the server's."""
    if remote_session():
        return []
    for name, command in WRITERS:
        if shutil.which(name):
            return command
    return []


def copy_to_system(text: str) -> str:
    """Put text on the real clipboard; returns the tool used."""
    command = clipboard_tool()
    if not command:
        return ""
    # clip.exe reads UTF-8 as the console code page (mojibake) and keeps a UTF-16
    # byte-order mark as a character; little-endian UTF-16 without one is exact.
    data = text.encode("utf-16-le") if command[0] in {"clip.exe", "clip"} else text.encode("utf-8")
    try:
        process = subprocess.run(command, input=data,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, timeout=5, env=external_environment())
    except (OSError, subprocess.SubprocessError):
        return ""
    return command[0] if process.returncode == 0 else ""


def osc52(text: str, env=None) -> str:
    """Ask the terminal showing Eirene, even across SSH, to set its own clipboard.

    tmux drops application OSC 52 unless `set-clipboard on`, and forwards it inside a
    DCS passthrough only with `allow-passthrough on`; send both so either works.
    """
    env = os.environ if env is None else env
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    sequence = f"\x1b]52;c;{encoded}\a"
    if env.get("TMUX"):
        return sequence + "\x1bPtmux;" + sequence.replace("\x1b", "\x1b\x1b") + "\x1b\\"
    if env.get("STY"):  # GNU screen
        # screen drops a DCS string longer than 768 bytes, which is any copy past
        # ~500 characters; it concatenates consecutive short ones instead.
        return "".join(f"\x1bP{sequence[start:start + SCREEN_CHUNK]}\x1b\\"
                       for start in range(0, len(sequence), SCREEN_CHUNK))
    return sequence
