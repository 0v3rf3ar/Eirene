"""Open transcript links on the desktop without the launcher touching the terminal.

Two hazards shape this module:

* Links come from model output, which can carry prompt-injected content. On
  Windows the shell "opens" a local path by running it, so a click on
  ``[docs](C:\\…\\tool.exe)`` would launch a program. Only web and mail links
  are handed to the desktop.
* ``webbrowser`` falls back to console browsers (lynx, w3m) when it finds no
  desktop, and those take over the terminal Eirene is drawing on. Launchers
  here never inherit the terminal and are never waited on from the event loop.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

from ..core.subprocesses import external_environment

LAUNCHABLE_SCHEMES = frozenset({"http", "https", "mailto"})
# Generous for real URLs (sign-in links run to a few KB) while bounding what
# reaches a shell API with its own length limits.
MAX_URL_CHARS = 8192
# Desktop handlers, best first. kde-open and exo-open cover desktops without xdg-utils.
POSIX_LAUNCHERS: tuple[tuple[str, ...], ...] = (
    ("xdg-open",),
    ("gio", "open"),
    ("kde-open",),
    ("exo-open", "--launch", "WebBrowser"),
)
LAUNCH_SECONDS = 10


class LinkError(Exception):
    """The desktop could not open a link."""


def launchable(url: str) -> bool:
    """Whether a link is safe to hand to the desktop's URL handler."""
    if not url or len(url) > MAX_URL_CHARS:
        return False
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    scheme = parts.scheme.lower()
    if scheme not in LAUNCHABLE_SCHEMES:
        return False
    return scheme == "mailto" or bool(parts.netloc)


def open_external(url: str) -> None:
    """Open a launchable URL in the desktop's handler; blocking, run it off the loop."""
    if not launchable(url):
        raise LinkError("only web and mail links can be opened")
    if os.name == "nt":
        try:
            os.startfile(url)  # type: ignore[attr-defined]  # noqa: S606 - scheme checked above
        except OSError as exc:
            raise LinkError(exc.strerror or str(exc)) from exc
        return
    if sys.platform == "darwin":
        _run(("open", url))
        return
    tried = []
    for launcher in POSIX_LAUNCHERS:
        if shutil.which(launcher[0]) is None:
            continue
        tried.append(launcher[0])
        try:
            _run((*launcher, url))
            return
        except LinkError:
            continue
    raise LinkError(f"{' and '.join(tried)} could not open it" if tried
                    else "no desktop link handler (xdg-open) is installed")


def _run(argv: tuple[str, ...]) -> None:
    """Launch detached from the terminal; a launcher still running has handed off."""
    try:
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True,
                                   env=external_environment())
    except OSError as exc:
        raise LinkError(exc.strerror or str(exc)) from exc
    try:
        code = process.wait(timeout=LAUNCH_SECONDS)
    except subprocess.TimeoutExpired:
        # Some handlers stay in the foreground for as long as the browser runs.
        return
    if code:
        raise LinkError(f"{argv[0]} exited with status {code}")


class OpensLinks:
    """Mixin for widgets that render Markdown links: handles their ``open_link`` click."""

    def action_open_link(self, url: str) -> None:
        self.app.open_url(url)  # type: ignore[attr-defined]
