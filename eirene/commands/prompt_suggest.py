"""Optional AI follow-up prompts."""

from . import register
from .switch import ask_on_off
from ..ui import art


@register("prompt-suggest", "configure AI follow-up suggestions", "/prompt-suggest [on|off]")
async def run(app, args):
    current = bool(app.config.get("prompt_suggest", False))
    status = app._suggestion_status if current else ""
    state = await ask_on_off(
        app, "prompt-suggest", args, current,
        on_hint=f"current · {status}" if current and status else "",
        on_detail="Draft a follow-up prompt after each reply; Tab or → accepts it. "
                  "One extra model request per reply.",
        off_detail="No follow-up drafts and no extra requests.")
    if state is None:
        return
    app.set_prompt_suggestions(state)
    app.say(f"{art.icon('ok')} prompt suggestions {'on' if state else 'off'}")
