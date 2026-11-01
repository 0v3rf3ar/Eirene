"""/pwd"""

from __future__ import annotations

from . import register


@register("pwd", "show the working directory")
async def run(app, args: str) -> None:
    app.say(str(app.sandbox.root))
