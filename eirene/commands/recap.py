"""/recap"""

from __future__ import annotations

from . import register
from .switch import ask_on_off
from ..ui import art


@register("recap", "turn session recaps on or off", "/recap [on|off]")
async def run(app, args: str) -> None:
    current = bool(app.config.get("recap", True))
    state = await ask_on_off(
        app, "recap", args, current,
        on_detail="A one-line recap after a turn once the chat grows by about two "
                  "screens. One extra model request each; never added to the chat.",
        off_detail="No recaps and no extra requests.")
    if state is None:
        return
    app.config.set("recap", state)
    app._save_config()
    app.say(f"{art.icon('ok')} recaps {'on' if state else 'off'}")
