"""Opt in to the graphical Eirene companion."""

from . import register
from ..core.errors import CommandError
from ..ui.companion import Companion


@register("companion", "toggle Eirene's animated companion", "/companion [on|off]")
async def run(app, args: str) -> None:
    if args not in {"", "on", "off"}:
        raise CommandError("use /companion [on|off]")
    if getattr(app, "_companion_renderer", None) is None:
        raise CommandError("this terminal cannot display the graphical companion")
    enabled = args == "on" if args else not app.config.get("companion", False)
    app.config.set("companion", enabled)
    app._save_config()
    companion = app.query_one(Companion)
    if enabled:
        companion.wake()
    companion.refresh_companion()
