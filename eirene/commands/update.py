"""User-requested application updates, separate from agent execution permissions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from rich.text import Text

from .. import __version__
from ..core import updates
from ..ui.terminal import copy_to_system
from . import register


@register("update", "install the latest stable release, or use edge for prereleases", "/update [edge] [check]")
async def run(app, args: str) -> None:
    args = args.strip()
    if args not in {"", "check", "edge", "edge check", "check edge"}:
        app.say("usage: /update [edge] [check]", "warn")
        return
    edge = "edge" in args.split()
    check_only = "check" in args.split()
    command = "/update edge" if edge else "/update"
    channel = "edge" if edge else "stable"
    if getattr(app, "_update_pending", False):
        app.say("An update is already installed or scheduled. Exit and restart Eirene.")
        return
    app.say(f"Checking GitHub for a new Eirene {channel} release…")
    try:
        release = await updates.check(edge=edge)
        if release is None:
            app.say(f"Eirene {__version__} is up to date on the {channel} channel.")
            return
        if check_only:
            app.say(f"Eirene {release.version} is available (current: {__version__}). Run {command} to install it.")
            return
        if updates.needs_installer():
            _show_windows_command(app, release)
            return
        app.say(f"Downloading Eirene {release.version}…")
        last_percent = -10

        def progress(count: int, total: int) -> None:
            nonlocal last_percent
            percent = int(count * 100 / total) if total else 0
            if total and percent >= last_percent + 10:
                last_percent = percent
                if not getattr(app.status, "active", False):
                    app.status.stop(f"Downloading update: {percent}%")

        staged = await updates.download(release, progress=progress)
        message = await asyncio.to_thread(updates.install, staged)
        app._update_pending = bool(getattr(sys, "frozen", False))
        app.say(message)
    except (updates.UpdateError, OSError, TimeoutError) as exc:
        app.say(f"Update failed: {exc}", "warn")
    finally:
        if not getattr(app.status, "active", False):
            app.status.stop()


def _show_windows_command(app, release: updates.Release) -> None:
    """Windows keeps a running eirene.exe locked, so the installer replaces it instead."""
    command = updates.windows_update_command(release, Path(sys.executable).resolve().parent)
    copied = bool(copy_to_system(command))
    app.say(f"Eirene {release.version} is available (current: {__version__}). "
            "Run the update command shown in the panel" + (" (copied to your clipboard)." if copied else "."))
    body = Text()
    body.append(f"Update to Eirene {release.version}\n\n", style="bold")
    body.append("Windows cannot replace eirene.exe while it is running. Run this in PowerShell,\n"
                "in any window, before or after you exit Eirene:\n\n")
    body.append(command + "\n\n", style="bold")
    body.append(f"It downloads {release.tag}, verifies its SHA-256 checksum, waits for every\n"
                "Eirene window to close, then replaces the executable. Start Eirene again\n"
                "afterwards; your sessions and settings are kept.")
    app.aside.show_content(body)
