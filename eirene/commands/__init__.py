"""Slash command registry and dispatch."""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import Awaitable, Callable

from ..core.errors import CommandError, EireneError

Handler = Callable[[object, str], Awaitable[None]]


@dataclass
class Command:
    """One slash command."""

    name: str
    summary: str
    usage: str
    handler: Handler
    wants_args: bool = False
    hidden: bool = False


REGISTRY: dict[str, Command] = {}


def register(name: str, summary: str, usage: str = "", wants_args: bool = False,
             *, hidden: bool = False):
    def wrap(handler: Handler) -> Handler:
        REGISTRY[name] = Command(name, summary, usage or f"/{name}", handler,
                                 wants_args, hidden)
        return handler
    return wrap


def lookup(name: str, app=None) -> Command | None:
    _load()
    if name == "plugin":
        name = "plugins"
    return REGISTRY.get(name) or next((command for command in commands(app) if command.name == name), None)


def _load() -> None:
    from . import (agents, btw, clear, compact, connect, exit as exit_cmd, plan, plugins,
                   help as help_cmd, keybindings, mcp, model, notification, schedule, sessions, skills,
                   permissions, review, sandbox, search_api, snow, prompt_suggest, tasks, theme, think, update, usage)  # noqa: F401


async def dispatch(app, text: str) -> None:
    """Route a slash command."""
    _load()
    body = text[1:].strip()
    if not body:
        app.say("type /help to see the commands", "warn")
        return
    parts = body.split(maxsplit=1)
    name, args = parts[0], parts[1] if len(parts) > 1 else ""
    name = name.lower()
    if name == "plugin":
        name = "plugins"
    if name == "udpate":
        name = "update"
    available = {**{command.name: command for command in commands(app)}, **REGISTRY}
    command = available.get(name)
    if command is None:
        close = difflib.get_close_matches(name, [c.name for c in commands(app)], n=1, cutoff=0.5)
        hint = f" - did you mean /{close[0]}?" if close else " - try /help"
        app.say(f"unknown command /{name}{hint}", "warn")
        return
    try:
        await command.handler(app, args.strip())
    except CommandError as exc:
        app.say(f"/{name}: {exc.user_message()}", "warn")
    except EireneError as exc:
        app.say(exc.user_message(), "fail")
    except Exception as exc:  # noqa: BLE001
        app.say(f"/{name} failed: {exc}", "fail")


def commands(app=None) -> list[Command]:
    _load()
    visible = sorted(name for name, command in REGISTRY.items() if not command.hidden)
    if app is None or getattr(app.config, "provider", None) != "ollama-local":
        visible = [name for name in visible if name != "think"]
    from .plugin_commands import commands as plugin_commands
    return [REGISTRY[name] for name in visible] + plugin_commands(getattr(app, "config", None))
