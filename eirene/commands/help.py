"""/help"""

from __future__ import annotations

from rich.text import Text

from ..ui import art
from ..ui.chat import Block
from . import commands, register
from ..ui.shortcuts import SHORTCUTS, EDITING_KEYS


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
    for key, meaning in [(label, hint) for _, _, label, hint in SHORTCUTS] + list(EDITING_KEYS):
        body.append(f"  {key:<{width}}  ", style="bold")
        body.append(f"{meaning}\n", style="dim")
    body.append("\n  tips\n", style="bold")
    for tip in ("Type / and filter commands; Tab fills one in, Enter runs it.",
                "Click command output to expand it and inspect the result.",
                "Send a follow-up while working to queue it for the next safe step."):
        body.append(f"  {tip}\n", style="dim")
    await app.push(Block(body))
