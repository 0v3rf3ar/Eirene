"""/exit"""

from __future__ import annotations

from . import register


@register("exit", "leave eirene")
async def run(app, args: str) -> None:
    app.action_leave()
