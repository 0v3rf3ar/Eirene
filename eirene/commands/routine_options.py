"""Choices shared by /schedule (new routine) and /routines (edit a routine)."""

from __future__ import annotations

import asyncio

from ..core.errors import CommandError, EireneError, SchedulerError
from ..providers import registry as providers
from ..scheduling.base import TOOL_GROUP_HELP, TOOL_GROUPS, parse_names, parse_tools

MODEL_LIST_TIMEOUT = 20
# Groups picked as tools; MCP access is chosen per server instead.
PLAIN_GROUPS = tuple(group for group in TOOL_GROUPS if group != "mcp")
MAX_LISTED = 12

TOOL_PRESETS = [
    ("read", "read only", "look and report; no changes"),
    ("read,edit", "read + edit files", "change files, no commands"),
    ("read,edit,commands", "edit + run commands", "build, test, script"),
    ("read,web", "read + web", "research; no changes"),
    ("all", "everything", ", ".join(PLAIN_GROUPS[1:])),
    ("custom", "custom…", "pick groups by name"),
]


class Cancelled(Exception):
    """The person backed out of a step."""


async def text(app, label: str, *, allow_empty: bool = False) -> str:
    value = await app.ask_text(label)
    if value is None or (not value.strip() and not allow_empty):
        raise Cancelled
    return value.strip()


async def choice(app, title: str, options: list[tuple]) -> str:
    value = await app.ask_choice(title, options)
    if not value:
        raise Cancelled
    return value


def with_mcp(tools: list[str], servers: list[str]) -> list[str]:
    """Tool groups with "mcp" present exactly when servers are granted."""
    chosen = {group for group in tools if group != "mcp"} | {"read"}
    if servers:
        chosen.add("mcp")
    return [group for group in TOOL_GROUPS if group in chosen]


# model

async def pick_model(app, title: str, *, keep: str = "") -> tuple[str, str] | None:
    """(provider, model) for a routine; ("", "") follows the active choice; None keeps it."""
    options = []
    if keep:
        options.append(("keep", f"keep: {keep}", "no change"))
    key, model = app.agent.provider_key or "", app.agent.model or ""
    if key and model:
        options.append(("current", f"{providers.display_name(key)} / {model}",
                        "the model you are using now, for every run"))
    options += [
        ("active", "whatever is active at run time",
         "follows /connect and /model; changes when you switch"),
        ("other", "another provider or model…", "pick from your saved connections"),
    ]
    picked = await choice(app, title, options)
    if picked == "keep":
        return None
    if picked == "current":
        return key, model
    if picked == "active":
        return "", ""
    saved = [name for name in app.config.configured_providers() if providers.available(name)]
    if not saved:
        raise CommandError("no saved provider connections; add one with /connect first")
    rows = [(name, providers.display_name(name),
             app.config.provider_config(name).get("model") or "") for name in saved]
    chosen = await choice(app, "provider for the routine", rows)
    return chosen, await pick_model_name(app, chosen)


async def pick_model_name(app, key: str) -> str:
    spec = providers.spec(key)
    names: list[str] = []
    try:
        provider = providers.build(key, app.config)
    except EireneError as exc:
        raise CommandError(exc.user_message()) from exc
    app.say(f"asking {spec.label} for its models…")
    try:
        names = list(await asyncio.wait_for(provider.models(), MODEL_LIST_TIMEOUT))
    except (EireneError, asyncio.TimeoutError) as exc:
        detail = exc.user_message() if isinstance(exc, EireneError) else "timed out"
        app.say(f"could not list models: {detail}", "warn")
        names = list(spec.models or [])
    finally:
        close = getattr(provider, "close", None)
        if close:
            await close()
    saved = app.config.provider_config(key).get("model") or ""
    options = [(name, name, "saved" if name == saved else "") for name in names]
    options.append(("__type", "type a model name…", ""))
    picked = await choice(app, f"{spec.label} model", options)
    if picked == "__type":
        picked = await text(app, f"{spec.label} model name")
    return picked


# tools, MCP servers, skills

async def pick_tools(app, title: str) -> list[str]:
    preset = await choice(app, title, TOOL_PRESETS)
    if preset == "custom":
        listing = ", ".join(f"{group} ({TOOL_GROUP_HELP[group]})" for group in PLAIN_GROUPS[1:])
        raw = await text(app, f"tools, comma separated: {listing}", allow_empty=True)
        preset = raw or "read"
    try:
        tools = parse_tools(preset.replace(",", " "))
    except SchedulerError as exc:
        raise CommandError(exc.user_message()) from exc
    return [group for group in tools if group != "mcp"]


def enabled_servers(config) -> list[str]:
    from ..core.plugins import merged_mcp_servers
    return sorted(merged_mcp_servers(config))


async def pick_mcp(app, title: str, *, keep: str = "") -> list[str] | None:
    """MCP servers the routine may call unattended; None keeps the current choice."""
    servers = enabled_servers(app.config)
    if not servers:
        app.say("no MCP servers are enabled; turn one on in /mcp to use it in a routine")
        return [] if not keep else None
    options = [("keep", f"keep: {keep}", "no change")] if keep else []
    options += [("none", "no MCP servers", "the routine cannot call MCP tools"),
                ("all", "every enabled server", _clip(", ".join(servers)))]
    if len(servers) > 1:
        options += [(name, name, "only this server") for name in servers[:MAX_LISTED]]
        options.append(("custom", "several…", "type server names"))
    else:
        options.append((servers[0], servers[0], "only this server"))
    picked = await choice(app, title + " (their tools run without asking)", options)
    if picked == "keep":
        return None
    if picked == "custom":
        picked = await text(app, "MCP servers, comma separated: " + ", ".join(servers))
    names = parse_names(picked)
    unknown = [name for name in names if name != "*" and name not in servers]
    if unknown:
        raise CommandError("not an enabled MCP server: " + ", ".join(unknown))
    return names


async def pick_skills(app, title: str, *, keep: str = "") -> tuple[bool, list[str] | None]:
    """(changed, skills): None follows /skills, [] none, ["*"] every installed skill."""
    from ..core import skills as skills_mod
    installed = skills_mod.apply_config(skills_mod.discover(), app.config)
    if not installed:
        return False, None
    on = [skill.name for skill in installed if skill.enabled]
    options = [("keep", f"keep: {keep}", "no change")] if keep else []
    options += [
        ("saved", "skills enabled in /skills",
         f"{len(on)} now" + (f": {_clip(', '.join(on))}" if on else "")),
        ("none", "no skills", "the routine loads none"),
        ("all", "every installed skill", f"{len(installed)} installed"),
    ]
    if len(installed) <= MAX_LISTED:
        options += [(skill.name, skill.name, _clip(skill.summary)) for skill in installed]
    options.append(("custom", "several…", "type skill names"))
    picked = await choice(app, title, options)
    if picked == "keep":
        return False, None
    if picked == "saved":
        return True, None
    if picked == "custom":
        picked = await text(app, "skills, comma separated: "
                            + _clip(", ".join(skill.name for skill in installed), 300))
    names = parse_names(picked)
    known = {skill.name for skill in installed}
    unknown = [name for name in names if name != "*" and name not in known]
    if unknown:
        raise CommandError("not an installed skill: " + ", ".join(unknown))
    return True, names


def _clip(value: str, limit: int = 70) -> str:
    value = " ".join(str(value or "").split())
    return value if len(value) <= limit else value[:limit - 1] + "…"
