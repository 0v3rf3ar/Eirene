"""Optional AI follow-up prompts."""
from . import register
from ..core.errors import CommandError
from rich.text import Text
from .usage import _styles, _append_box_line, _append_rule


@register("prompt-suggest", "configure AI follow-up suggestions", "/prompt-suggest [on|off]")
async def run(app, args):
    if args not in {"", "on", "off"}:
        raise CommandError("use /prompt-suggest [on|off]")
    if args:
        app.set_prompt_suggestions(args == "on")
    show(app)


def show(app):
    styles = _styles(app)
    width = 62
    enabled = app.config.get("prompt_suggest", False)
    body = Text("╭─ prompt suggestions " + "─" * 42 + "╮\n", style=styles["heading"])
    for label, value in [("Setting", "ON" if enabled else "OFF (default)"),
                         ("Status", app._suggestion_status if enabled else "Disabled")]:
        line = Text(f"{label:<12}", style=styles["muted"])
        line.append(value, style=styles["value"])
        line.truncate(width - 2, overflow="ellipsis")
        _append_box_line(body, line, width, styles)
    _append_rule(body, width, styles)
    for line in ["Prepared while answering; revealed when the reply ends.",
                 "Tab or → copies it into an empty input; Enter sends.",
                 "Uses an extra model request. Never submits automatically."]:
        _append_box_line(body, line, width, styles, styles["muted"])
    body.append("╰" + "─" * width + "╯", style=styles["frame"])
    app.aside.show_toggle(body, enabled, app.set_prompt_suggestions)
