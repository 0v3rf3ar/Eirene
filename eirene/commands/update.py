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


class _View:
    """The update card in the interface; plain lines anywhere else (headless)."""

    def __init__(self, app, channel: str):
        self.app = app
        self.channel = channel
        self.card = None
        self.size = 0

    async def open(self) -> None:
        if hasattr(self.app, "transcript") and hasattr(self.app, "push"):
            from ..ui.update_card import UpdateCard
            self.card = await self.app.push(UpdateCard(__version__, self.channel))

    def step(self, text: str, state: str = "ok") -> None:
        if self.card is not None:
            self.card.step(text, state)
        elif state != "busy":
            self.app.say(text, "warn" if state == "fail" else "info")

    def found(self, version: str) -> None:
        if self.card is not None:
            self.card.found(version)

    def progress(self, count: int, total: int) -> None:
        self.size = total or count
        if self.card is not None:
            self.card.progress(count, total)

    def finish(self, footer: str) -> None:
        if self.card is not None:
            self.card.finish(footer)
        else:
            self.app.say(footer)


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
        app.say("An update is already installed. Run /restart to use it.")
        return
    view = _View(app, channel)
    await view.open()
    view.step("Checking GitHub", "busy")
    try:
        release = await updates.check(edge=edge)
        if release is None:
            view.step("Checked GitHub")
            view.finish(f"Eirene {__version__} is up to date on the {channel} channel.")
            return
        view.found(release.version)
        view.step(f"Found Eirene {release.version}")
        if check_only:
            view.finish(f"Eirene {release.version} is available (current: {__version__}). "
                        f"Run {command} to install it.")
            return
        if updates.needs_installer():
            view.finish(_show_windows_command(app, release))
            return
        view.step(f"Downloading Eirene {release.version}", "busy")
        staged = await updates.download(release, progress=view.progress)
        size = f" ({view.size / 1_000_000:.1f} MB)" if view.size else ""
        view.step(f"Downloaded{size}")
        view.step("SHA-256 checksum verified")
        view.step("Installing", "busy")
        message = await asyncio.to_thread(updates.install, staged)
        frozen = bool(getattr(sys, "frozen", False))
        app._update_pending = frozen
        if frozen:
            view.step("Installed")
            view.finish(f"Run /restart to start Eirene {release.version}.")
        else:
            view.finish(message)
    except (updates.UpdateError, OSError, TimeoutError) as exc:
        view.step(f"Update failed: {exc}", "fail")
    finally:
        if not getattr(app.status, "active", False):
            app.status.stop()


def _show_windows_command(app, release: updates.Release) -> str:
    """Windows keeps a running eirene.exe locked, so the installer replaces it instead."""
    command = updates.windows_update_command(release, Path(sys.executable).resolve().parent)
    copied = bool(copy_to_system(command))
    body = Text()
    body.append(f"Update to Eirene {release.version}\n\n", style="bold")
    body.append("Windows cannot replace eirene.exe while it is running. Run this in PowerShell,\n"
                "in any window, before or after you exit Eirene:\n\n")
    body.append(command + "\n\n", style="bold")
    body.append(f"It downloads {release.tag}, verifies its SHA-256 checksum, waits for every\n"
                "Eirene window to close, then replaces the executable. Start Eirene again\n"
                "afterwards; your sessions and settings are kept.")
    app.aside.show_content(body)
    return (f"Eirene {release.version} is available (current: {__version__}). "
            "Run the update command shown in the panel"
            + (" (copied to your clipboard)." if copied else "."))
