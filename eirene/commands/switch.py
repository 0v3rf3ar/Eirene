"""Shared on/off handling for commands that flip one setting."""

from __future__ import annotations

from ..core.errors import CommandError

ON = {"on", "enable", "enabled", "yes", "true", "1"}
OFF = {"off", "disable", "disabled", "no", "false", "0"}


async def ask_on_off(app, title: str, args: str, current: bool, *,
                     on_detail: str = "", off_detail: str = "",
                     on_hint: str = "") -> bool | None:
    """The wanted state from the arguments, or from the usual picker menu.

    None means the menu was dismissed without a choice.
    """
    wanted = args.strip().lower()
    if wanted in ON:
        return True
    if wanted in OFF:
        return False
    if wanted:
        raise CommandError(f"use /{title} on or /{title} off")
    options = [
        ("on", "On", on_hint or ("current" if current else ""), on_detail),
        ("off", "Off", "current" if not current else "", off_detail),
    ]
    chosen = await app.ask_choice(title, options, selected="on" if current else "off")
    if chosen is None:
        return None
    return chosen == "on"
