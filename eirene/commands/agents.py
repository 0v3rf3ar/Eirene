"""/agents"""

from __future__ import annotations

from ..core.modes import Mode
from ..ui import art
from . import register


@register("agents", "change mode or list plugin specialists", "/agents [auto|manual|plan|list]")
async def run(app, args: str) -> None:
    wanted = args.strip().lower()
    if wanted == "list":
        from ..core.plugin_resources import agent_definitions
        profiles = agent_definitions(app.config)
        if not profiles:
            app.say("no enabled plugin specialists; install feature-dev or pr-review-toolkit")
            return
        app.say("Plugin specialists (delegate_tasks uses these names):\n" + "\n".join(
            f"{name} — {fields.get('description', '')[:240]}\n"
            f"  /{plugin.name}:agent-{path.stem} [task]"
            for name, (plugin, path, fields, _) in profiles.items()))
        return
    if wanted:
        for mode in Mode:
            if mode.value.startswith(wanted):
                _apply(app, mode)
                return
        app.say(f"no mode called '{wanted}'; try auto, manual or plan", "warn")
        return

    options = [(mode.value, f"{mode.icon} {mode.label}",
                mode.blurb + (" (current)" if mode is app.agent.mode else ""))
               for mode in Mode]
    chosen = await app.ask_choice("which mode?", options,
                                  selected=app.agent.mode.value)
    if chosen:
        _apply(app, Mode(chosen))


def _apply(app, mode: Mode) -> None:
    app.agent.mode = mode
    app.config.mode = mode.value
    app._save_config()
    app.refresh_mode_line()
    app.say(f"{art.icon('ok')} {mode.label}: {mode.blurb}")
