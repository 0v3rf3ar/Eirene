"""/restart"""

from __future__ import annotations

from . import register


@register("restart", "restart Eirene, keeping this session")
async def run(app, args: str) -> None:
    app.action_leave(restart=True)
