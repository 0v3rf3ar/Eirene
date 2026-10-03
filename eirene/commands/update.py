"""User-requested application updates, separate from agent execution permissions."""

from __future__ import annotations

import asyncio
import sys

from .. import __version__
from ..core import updates
from . import register


@register("update", "check GitHub and download/install the latest release", "/update [check]")
async def run(app, args: str) -> None:
    if args not in {"", "check"}:
        app.say("usage: /update [check]", "warn")
        return
    if getattr(app, "_update_pending", False):
        app.say("An update is already installed or scheduled. Exit and restart Eirene.")
        return
    app.say("Checking GitHub for a new Eirene release…")
    try:
        release = await updates.check()
        if release is None:
            app.say(f"Eirene {__version__} is up to date.")
            return
        if args == "check":
            app.say(f"Eirene {release.version} is available (current: {__version__}). Run /update to install it.")
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
