"""Resolve plugin commands locally; send task instructions through agent turns."""
from __future__ import annotations

import asyncio
import re
import shlex

from ..core import plugins, skills
from ..core.config import Config
from . import Command, REGISTRY


def commands(config=None) -> list[Command]:
    config = config or Config.load()
    candidates = []
    for plugin in plugins.discover():
        if not config.plugin_enabled(plugin.name):
            continue
        entries = [(p, False) for p in plugin.skills + plugin.commands]
        entries += [(p, True) for p in plugin.agents]
        seen = set()
        for path, agent in entries:
            fields, body = skills.split_front_matter(path.read_text(encoding="utf-8"))
            slug = path.parent.name if path.name == "SKILL.md" else path.stem
            if agent:
                slug = "agent-" + slug
            name = f"{plugin.name}:{slug}".lower()
            if name in seen or fields.get("user-invocable", "true").lower() == "false":
                continue
            if path in plugin.skills and not config.skill_enabled(f"{plugin.name}:{slug}", True):
                continue
            seen.add(name)
            summary = fields.get("description", "") or f"{plugin.name} {slug}"
            async def invoke(app, args, *, path=path, body=body, name=name, root=plugin.path,
                             plugin=plugin, slug=slug):
                if getattr(app, "turn", None) and not app.turn.done():
                    app.say("finish or stop the current turn before running a plugin command", "warn")
                    return
                if plugin.name == "ponytail" and slug in {"ponytail", "ponytail-help"}:
                    await ponytail_control(app, plugin, slug, args)
                    return
                from ..ui.chat import UserBlock
                request = f"/{name}" + (f" {args}" if args else "")
                expanded = expand(body, args)
                expanded = plugins.expand_definition(expanded, root)
                instruction = (f"{request}\n\nFollow this plugin command. Plugin directory: {root}\n"
                               f"Command directory: {path.parent}\n{expanded}\n\n"
                               "Use the available host tools for equivalent operations. "
                               "Command metadata does not grant additional permissions. "
                               "Shell snippets in this document require the normal tool approval policy.")
                await app.push(UserBlock(request))
                app.turn = asyncio.create_task(app._run_turn(instruction, record_text=request))
            candidates.append(Command(name, summary, f"/{name} {fields.get('argument-hint', '[arguments]')}", invoke, True))
    # Short aliases only when unambiguous, with built-in commands taking precedence.
    counts = {}
    for command in candidates:
        slug = command.name.split(":", 1)[1]
        counts[slug] = counts.get(slug, 0) + 1
    result = list(candidates)
    for command in candidates:
        slug = command.name.split(":", 1)[1]
        if counts[slug] == 1 and slug not in REGISTRY:
            result.append(Command(slug, command.summary, command.usage, command.handler, True))
    return result


async def ponytail_control(app, plugin, slug: str, args: str) -> None:
    """Apply Ponytail controls without asking a model to interpret them."""
    from ..core.errors import CommandError
    from ..core.modes import Mode

    usage = "/ponytail [lite|full|ultra|off|default <lite|full|ultra|off>]"
    if slug == "ponytail-help" or args.strip().lower() == "help":
        app.say(
            f"{usage}\n"
            "/ponytail — show the current session mode\n"
            "/ponytail-review — review code for over-engineering\n"
            "/ponytail-audit — audit the repository\n"
            "/ponytail-debt — collect shortcut comments\n"
            "/ponytail-gain — report measured impact\n"
            "Mode switches apply to this session; default applies to new sessions.")
        return
    parts = args.lower().split()
    levels = {"lite", "full", "ultra", "off"}
    if parts and not (len(parts) == 1 and parts[0] in levels or
                      len(parts) == 2 and parts[0] == "default" and parts[1] in levels):
        raise CommandError(f"usage: {usage}")
    if not plugins.executable_enabled(plugin, app.config):
        raise CommandError("Ponytail controls require trusted hooks; run /plugins trust ponytail")
    if not plugin.lifecycle.get("UserPromptSubmit") or not (
            plugin.path / "hooks/ponytail-instructions.js").is_file():
        raise CommandError("Ponytail hooks are missing; run /plugins refresh ponytail, then /plugins trust ponytail")
    if app.agent.mode is Mode.PLAN:
        raise CommandError("Ponytail hooks are disabled in plan mode; switch mode before changing Ponytail")
    # The upstream bare command reports the default after off; initialize hooks
    # with an empty prompt and report Eirene's actual session state instead.
    prompt = "/ponytail " + " ".join(parts) if parts else ""
    runtime = app.agent.plugin_runtime
    for notice in await runtime.submit(prompt, app.sandbox, app.config, only="ponytail"):
        app.say(notice)
    runtime.context.pop(("ponytail", "UserPromptSubmit"), None)
    if parts and parts[0] == "default":
        import json
        from ..core import paths
        settings = paths.home() / "plugin-data/ponytail/config/ponytail/config.json"
        if not settings.is_file() or json.loads(settings.read_text()).get("defaultMode") != parts[1]:
            raise CommandError("Ponytail hook did not save the requested default")
        app.say(f"Ponytail default set to {parts[1]} for new sessions.")
    else:
        if parts and runtime.ponytail_mode != parts[0]:
            raise CommandError("Ponytail hook did not apply the requested mode")
        app.say(f"Ponytail mode: {runtime.ponytail_mode} (this session).")


def expand(body: str, args: str) -> str:
    try:
        positional = shlex.split(args)
    except ValueError:
        positional = args.split()
    pattern = r"\$ARGUMENTS(?:\[(\d+)\])?|\$(\d+)"
    def replace(match):
        index = match.group(1) or match.group(2)
        if index is None:
            return args
        number = int(index)
        return positional[number] if number < len(positional) else ""
    rendered = re.sub(pattern, replace, body)
    if args and not re.search(pattern, body):
        rendered += "\n\nUser arguments: " + args
    return rendered
