"""/fast: the same model on a faster, pricier serving tier."""

from __future__ import annotations

from ..core.errors import CommandError
from ..providers import registry as providers
from ..ui import art
from . import register
from .switch import OFF, ask_on_off

# Where each backend offers a fast tier, for the hint when this model has none.
WHERE = {
    "anthropic": "Claude Opus 5.5, Opus 5 or Opus 4.8 on api.anthropic.com",
    "claude-code": "the opus model",
    "chatgpt": "GPT-5 and GPT-6 models, GPT-4.1, GPT-4o, o3 or o4-mini",
    "chatgpt-plan": "models your ChatGPT plan lists with a Fast tier",
    "chatgpt-subscription": "models Codex lists with a Fast tier",
}


@register("fast", "faster output from the same model, at a higher price",
          "/fast [on|off|status]")
async def run(app, args: str) -> None:
    agent = app.agent
    current = bool(app.config.get("fast_mode", False))
    wanted = args.strip().lower()
    supported = await _supported(app)
    if wanted == "status":
        app.say(_status(app, supported))
        return
    if not supported and wanted not in OFF:
        # Turning it off always works, so a saved choice is never stuck.
        raise CommandError(_unavailable(app))
    state = await ask_on_off(
        app, "fast", args, current,
        on_detail="Same model and quality, up to about 2x faster output, billed at the "
                  "provider's higher fast rate. Applies from the next request.",
        off_detail="Standard speed and pricing.")
    if state is None:
        return
    app.config.set("fast_mode", state)
    app._save_config()
    agent.set_fast(state)
    app.refresh_mode_line()
    if not state:
        app.say(f"{art.icon('ok')} fast mode off")
        return
    note = f"{art.icon('ok')} fast mode on · {_where(app)}"
    if any(message.get("role") == "assistant" for message in app.session.messages):
        # Fast and standard keep separate prompt caches.
        note += " · the first fast request re-reads this conversation uncached"
    app.say(note)


async def _supported(app) -> bool:
    agent = app.agent
    if agent.provider is None or not agent.model:
        return False
    try:
        check = getattr(agent.provider, "check_fast", None)
        return bool(check and await check(agent.model))
    except Exception as exc:  # noqa: BLE001 - a catalog hiccup is not fatal
        raise CommandError(f"could not check fast mode support: {exc}") from exc


def _where(app) -> str:
    agent = app.agent
    name = providers.display_name(agent.provider_key, compact=True) if agent.provider_key else ""
    return f"{name}({agent.model})" if name else agent.model


def _unavailable(app) -> str:
    agent = app.agent
    if not agent.provider_key:
        return "fast mode needs a provider; run /connect first"
    where = WHERE.get(providers.resolve_alias(agent.provider_key))
    hint = f"; it works with {where}" if where else ""
    return f"{_where(app)} has no fast tier{hint}"


def _status(app, supported: bool) -> str:
    if not app.config.get("fast_mode", False):
        return "fast mode off" + ("" if supported else f" · {_unavailable(app)}")
    if not supported:
        return f"fast mode on, but {_unavailable(app)} · standard speed"
    if app.agent.fast_state() == "cooling":
        return f"fast mode on · {_where(app)} is at standard speed until the fast limit cools down"
    return f"fast mode on · {_where(app)}"
