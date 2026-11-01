"""Non-executing diagnostics for installed plugin prerequisites and activation."""
from __future__ import annotations

import os
import re
import shutil

from . import plugins

PREREQUISITES = {
    "ponytail": ("node",), "superpowers": ("bash", "git"),
    "code-review": ("git", "gh"), "commit-commands": ("git", "gh"),
    "pr-review-toolkit": ("git", "gh"), "feature-dev": ("git",),
    "playwright": ("node", "npx"), "serena": ("uvx", "git"),
    "omniroute": ("omniroute",),
}


def report(plugin, config, *, provider=None):
    rows = [f"{plugin.name}: {'enabled' if config.plugin_enabled(plugin.name) else 'disabled (/plugins)'}"]
    requirements = set(PREREQUISITES.get(plugin.name, ()))
    for definition in plugin.mcp_servers.values():
        command = definition.get("command", [])
        if command:
            requirements.add(command[0] if isinstance(command, list) else command)
    for hooks in plugin.lifecycle.values():
        for hook in hooks:
            command = hook["command"]
            match = re.match(r"\s*(node|python3?|bash|sh|npx|uvx)\b", command)
            if match:
                requirements.add(match.group(1))
    rows += [f"  {name}: {'found' if shutil.which(name) else 'missing on PATH'}" for name in sorted(requirements)]
    if any(plugin.lifecycle.values()):
        rows.append("  Hooks: " + ("trusted" if plugins.executable_enabled(plugin, config)
                    else f"disabled; /plugins trust {plugin.name}"))
    for name, definition in plugins.available_mcp_servers(config).items():
        if definition["_plugin"] == plugin.name:
            rows.append(f"  MCP {name}: " + ("enabled" if config.get("mcp_enabled", {}).get(name)
                        else "disabled; enable with /mcp"))
            if definition.get("eirene_adapter"):
                rows.append(f"  MCP packages and caches: {plugins.paths.home() / 'plugin-data' / plugin.name / 'mcp'}")
    if provider is not None and not (provider.supports_tools or getattr(provider, "owns_context", False)):
        rows.append("  Provider supports text only: executable workflows and MCP need a tool-capable provider")
    if plugin.name in {"skills", "anthropic-skills"}:
        rows.append("  Document/artifact skills have individual Python, Node.js, rendering and font prerequisites; read their SKILL.md files")
    if plugin.name == "playwright":
        rows.append("  Browser binaries/system libraries must be installed; the MCP browser-install tool can install supported binaries")
    if plugin.name == "serena":
        rows.append("  Serena selects Python 3.13 and the current project; language-server prerequisites vary by language")
    if os.name == "nt" and plugin.name == "superpowers":
        rows.append("  Startup hook needs Git Bash (the upstream .cmd wrapper selects it)")
    rows.extend("  Compatibility: " + warning for warning in plugin.warnings)
    return "\n".join(rows)
