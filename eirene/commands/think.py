"""/think"""

from __future__ import annotations

from ..core.errors import CommandError
from ..providers import registry as providers
from ..ui import art
from . import register

THINK = {"think", "on", "yes", "true", "1"}
NO_THINK = {"nothink", "off", "no", "false", "0"}


@register("think", "set thinking for the local Ollama model",
          "/think [think|nothink]")
async def run(app, args: str) -> None:
    if not app.config.provider:
        raise CommandError("no provider yet - run /connect first")
    key = providers.resolve_alias(app.config.provider)
    if key != "ollama-local":
        raise CommandError("only available with the local Ollama provider")

    entry = app.config.provider_config(key)
    current = bool(entry.get("think", True))
    wanted = args.strip().lower()
    if not wanted:
        state = not current
    elif wanted in THINK:
        state = True
    elif wanted in NO_THINK:
        state = False
    else:
        raise CommandError("say /think think or /think nothink")

    entry["think"] = state
    app._save_config()
    app.agent.use(providers.build(key, app.config), key, app.agent.model)
    app.say(f"{art.icon('ok')} Ollama mode: {'think' if state else 'nothink'}")
