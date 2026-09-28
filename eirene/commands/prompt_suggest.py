"""Optional AI follow-up prompts."""
from . import register
from ..core.errors import CommandError
from rich.text import Text


@register("prompt-suggest", "configure AI follow-up suggestions", "/prompt-suggest [on|off]")
async def run(app, args):
    if args not in {"", "on", "off"}:
        raise CommandError("use /prompt-suggest [on|off]")
    if args:
        app.set_prompt_suggestions(args == "on")
    show(app)


def show(app):
    enabled = app.config.get("prompt_suggest", False)
    body = Text()
    body.append("Prompt suggestions\n", style="bold")
    body.append(app._suggestion_status if enabled else "Disabled", style="dim")
    body.append("\n\nExtra model request", style="dim")
    app.aside.show_toggle(body, enabled, app.set_prompt_suggestions)
