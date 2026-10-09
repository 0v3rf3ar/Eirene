"""/model"""

from __future__ import annotations

from ..core.errors import CommandError, EireneError
from ..providers import registry as providers
from ..ui import art
from . import register


@register("model", "list and pick a model for the current provider", "/model [name]")
async def run(app, args: str) -> None:
    key = app.config.provider
    if not key:
        raise CommandError("no provider yet - run /connect first")
    key = providers.resolve_alias(key)
    spec = providers.spec(key)

    try:
        provider = providers.build(key, app.config)
    except EireneError as exc:
        raise CommandError(exc.user_message()) from exc

    wanted = args.strip()
    if wanted:
        await _use(app, key, wanted)
        return

    app.say(f"asking {spec.label} for its models…")
    try:
        names = await provider.models()
    except EireneError as exc:
        app.say(f"could not list models: {exc.user_message()}", "warn")
        names = spec.models
    if not names:
        raise CommandError("no models available")

    current = app.agent.model
    options = [(name, name, "current" if name == current else "") for name in names]
    chosen = await app.ask_choice(f"{spec.label} models ({len(names)})", options,
                                  selected=current)
    if chosen:
        await _use(app, key, chosen)


async def _use(app, key: str, model: str) -> None:
    provider = providers.build(key, app.config)
    if key == "chatgpt-plan":
        from .connect import _choose_reasoning
        try:
            if not await _choose_reasoning(app, provider, key, model):
                return
        finally:
            await provider.close()
    app.config.model = model
    app.config.set_provider(key, model=model)
    app._save_config()
    app.agent.use(providers.build(key, app.config), key, model)
    app.refresh_mode_line()
    app.say(f"{art.icon('ok')} using {model}")
