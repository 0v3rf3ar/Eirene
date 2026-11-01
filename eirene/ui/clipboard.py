"""Read a picture from the desktop clipboard, so pasting a screenshot attaches it.

Terminals only ever paste text, so Eirene asks the desktop for the image itself:
wl-paste on Wayland, xclip on X11, osascript on macOS and PowerShell on Windows
and WSL. Over SSH that desktop is the server's, not the user's, so nothing is
read there and the paste key keeps its ordinary text behaviour.

Nothing here raises: a missing tool, an empty clipboard or a slow helper all
mean "no image".
"""

from __future__ import annotations

import base64
import io
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.subprocesses import external_environment
from .terminal import remote_session

# Formats every vision provider accepts, best first.
NATIVE_TYPES = ("image/png", "image/jpeg", "image/webp", "image/gif")
# Formats some desktops offer instead; converted to PNG.
CONVERTIBLE_TYPES = ("image/bmp", "image/x-bmp", "image/tiff")
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
HELPER_SECONDS = 10
WSL_POWERSHELL = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
# Browsers and image editors also publish a lossless "PNG" format; the plain
# bitmap that GetImage reads has no alpha channel, so transparency would be lost.
POWERSHELL_SCRIPT = (
    "Add-Type -AssemblyName System.Windows.Forms; Add-Type -AssemblyName System.Drawing; "
    "$png = [System.Windows.Forms.Clipboard]::GetData('PNG'); "
    "if ($png -is [System.IO.MemoryStream]) { [Convert]::ToBase64String($png.ToArray()); exit 0 }; "
    "$image = [System.Windows.Forms.Clipboard]::GetImage(); if ($null -eq $image) { exit 1 }; "
    "$stream = New-Object System.IO.MemoryStream; "
    "$image.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png); "
    "[Convert]::ToBase64String($stream.ToArray())")


@dataclass(frozen=True)
class ClipboardImage:
    data: bytes
    mime_type: str

    @property
    def filename(self) -> str:
        return f"pasted-image.{EXTENSIONS[self.mime_type]}"


def read_image() -> ClipboardImage | None:
    """The picture on this desktop's clipboard, or None. Blocking: run it off the loop."""
    if remote_session():
        return None
    try:
        if sys.platform == "darwin":
            return _macos()
        if os.name == "nt" or _wsl():
            return _windows()
        return _wayland() or _x11()
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _wayland() -> ClipboardImage | None:
    if not os.environ.get("WAYLAND_DISPLAY") or shutil.which("wl-paste") is None:
        return None
    offered = _run(["wl-paste", "--list-types"])
    chosen = _choose(offered.decode("utf-8", "replace").split() if offered else [])
    return _normalise(_run(["wl-paste", "--no-newline", "--type", chosen]), chosen) if chosen else None


def _x11() -> ClipboardImage | None:
    if not os.environ.get("DISPLAY") or shutil.which("xclip") is None:
        return None
    offered = _run(["xclip", "-selection", "clipboard", "-t", "TARGETS", "-o"])
    chosen = _choose(offered.decode("utf-8", "replace").split() if offered else [])
    if not chosen:
        return None
    return _normalise(_run(["xclip", "-selection", "clipboard", "-t", chosen, "-o"]), chosen)


def _macos() -> ClipboardImage | None:
    with tempfile.TemporaryDirectory(prefix="eirene-clipboard-") as directory:
        target = Path(directory) / "clipboard.png"
        # «class PNGf» is the clipboard's PNG flavour; macOS converts screenshots to it.
        script = [
            "set png_data to (the clipboard as «class PNGf»)",
            f'set fp to open for access POSIX file "{target}" with write permission',
            "write png_data to fp",
            "close access fp",
        ]
        argv = ["osascript"] + [part for line in script for part in ("-e", line)]
        if _run(argv) is None or not target.is_file():
            return None
        return _normalise(target.read_bytes(), "image/png")


def _windows() -> ClipboardImage | None:
    executable = shutil.which("powershell.exe") or shutil.which("powershell")
    if executable is None and _wsl() and Path(WSL_POWERSHELL).is_file():
        executable = WSL_POWERSHELL
    if executable is None:
        return None
    # The clipboard is a single-threaded-apartment COM object: -Sta is required.
    output = _run([executable, "-NoProfile", "-NonInteractive", "-Sta", "-Command",
                   POWERSHELL_SCRIPT])
    if not output:
        return None
    return _normalise(base64.b64decode(output.strip(), validate=True), "image/png")


def _choose(offered: list[str]) -> str | None:
    offered_types = {item.strip().lower() for item in offered}
    return next((kind for kind in NATIVE_TYPES + CONVERTIBLE_TYPES if kind in offered_types), None)


def _normalise(data: bytes | None, mime_type: str) -> ClipboardImage | None:
    """Keep provider-ready formats; convert the rest to PNG. Unreadable data is no image."""
    if not data:
        return None
    if mime_type in NATIVE_TYPES:
        return ClipboardImage(data, mime_type)
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as picture:
            converted = io.BytesIO()
            picture.save(converted, format="PNG")
    except Exception:  # noqa: BLE001 - Pillow raises many types for bad input
        return None
    return ClipboardImage(converted.getvalue(), "image/png")


def _run(argv: list[str]) -> bytes | None:
    """stdout of a helper that succeeded, else None; never attached to the terminal."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                timeout=HELPER_SECONDS, env=external_environment(),
                                creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _wsl() -> bool:
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError:
        return False
