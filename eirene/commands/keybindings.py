"""Quick keyboard reference."""
from rich.text import Text

from . import register
from ..ui.shortcuts import SHORTCUTS, EDITING_KEYS


@register("keybindings", "show keyboard shortcuts")
async def run(app, args: str) -> None:
    body = Text()
    body.append("Keybindings\n\n", style="bold")
    for key, meaning in [(label, hint) for _, _, label, hint in SHORTCUTS] + list(EDITING_KEYS):
        body.append(f"{key:<18}", style="bold")
        body.append(f"{meaning}\n", style="dim")
    body.remove_suffix("\n")
    app.aside.show_content(body)
