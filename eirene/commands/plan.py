"""/plan"""

from __future__ import annotations

from rich.text import Text

from ..core import plans
from ..ui.chat import Block
from . import register


@register("plan", "show or clear the durable project plan", "/plan [clear]")
async def run(app, args: str) -> None:
    action = args.strip().lower()
    if action == "clear":
        confirmed = await app.ask_choice("clear the project plan?",
                                         [("yes", "clear it", "cannot be undone"),
                                          ("no", "cancel", "")])
        if confirmed == "yes":
            app.say(plans.clear(app.sandbox.root))
        return
    await app.push(Block(Text(plans.load(app.sandbox.root).render())))
