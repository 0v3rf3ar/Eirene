"""/clear"""

from __future__ import annotations

from . import register


@register("clear", "wipe the session; nothing is kept on exit")
async def run(app, args: str) -> None:
    app.clear_session()
