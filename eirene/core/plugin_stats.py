"""The table on the Stats tab of /plugins. Reads what is installed; runs nothing."""

from __future__ import annotations

from . import plugins, skills

COLUMNS = (("Skills", 6), ("Cmds", 4), ("Hooks", 5), ("MCP", 3), ("Tokens", 6), ("State", 9))


def _tokens(count: int) -> str:
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)


def _columns(*values) -> str:
    return "  ".join(f"{value or '–':>{width}}" for value, (_, width) in zip(values, COLUMNS))


def state(name: str, config) -> str:
    if not config.plugin_trusted(name):
        return "untrusted"
    return "on" if config.plugin_enabled(name) else "off"


def table(config, found=None) -> tuple[list[tuple[str, str]], list[tuple]]:
    """(header lines, one row per plugin); a row opens that plugin's actions."""
    found = plugins.discover() if found is None else found
    every_skill = skills.apply_config(skills.discover(), config)
    available = plugins.available_mcp_servers(config)
    switches = config.get("mcp_enabled", {})
    servers = [name for name, definition in available.items() if plugins.mcp_on(name, definition, switches)]
    active = [skill for skill in every_skill if skill.enabled]
    summary = (f"Active: {sum(config.plugin_active(p.name) for p in found)}/{len(found)} plugins · "
               f"{len(active)}/{len(every_skill)} skills · {len(servers)}/{len(available)} MCP · "
               f"~{_tokens(sum(skill.tokens for skill in active))} tokens")
    header = [(summary, ""), ("", ""), ("Plugin", "  ".join(f"{name:>{width}}" for name, width in COLUMNS))]
    rows = []
    for plugin in found:
        members = [skill for skill in every_skill if skill.group == plugin.name]
        tokens = sum(skill.tokens for skill in members)
        rows.append(("installed:" + plugin.name, plugin.name, _columns(
            len(members), len(plugin.commands), sum(len(group) for group in plugin.lifecycle.values()),
            len(plugin.mcp_servers), _tokens(tokens) if tokens else 0,
            state(plugin.name, config)), plugin.description))
    return header, rows
