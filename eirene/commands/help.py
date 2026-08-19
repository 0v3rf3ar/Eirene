"""/help"""

from __future__ import annotations

from rich.text import Text

from ..ui import art
from ..ui.chat import Block
from . import commands, register


@register("help", "show this menu")
async def run(app, args: str) -> None:
    body = Text()
    body.append(f"{art.icon('info')} commands\n", style="bold")
    available = commands(app)
    width = max(len(c.usage) for c in available)
    for command in available:
        body.append(f"  {command.usage:<{width}}  ", style="bold")
        body.append(f"{command.summary}\n", style="dim")
    body.append("\n  keys\n", style="bold")
    for key, meaning in (("shift + tab", "change mode (auto / manual / plan)"),
                         ("esc", "stop, or close whatever is open"),
                         ("ctrl + d", "exit"),
                         ("up / down", "recall what you typed"),
                         ("\\ then enter", "start a new line"),
                         ("mouse wheel", "scroll the transcript")):
        body.append(f"  {key:<{width}}  ", style="bold")
        body.append(f"{meaning}\n", style="dim")
    await app.push(Block(body))
