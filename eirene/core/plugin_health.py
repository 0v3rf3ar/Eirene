"""Non-executing diagnostics for installed plugin prerequisites and activation."""
from __future__ import annotations

import os
import re
import shutil

from . import plugins

PREREQUISITES = {
    "ponytail": ("node",), "superpowers": ("bash", "git"),
    "pr-review-toolkit": ("git", "gh"), "feature-dev": ("git",),
    "playwright": ("node", "npx"), "serena": ("uvx", "git"),
    "omniroute": ("omniroute",), "arena": ("python" if os.name == "nt" else "python3",),
}


def report(plugin, config, *, provider=None):
    status = ("not trusted; nothing runs until /plugins trust " + plugin.name if not config.plugin_trusted(plugin.name)
              else "on" if config.plugin_enabled(plugin.name) else "trusted but disabled (/plugins)")
    rows = [f"{plugin.name}: {status}"]
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
    for name, definition in plugins.available_mcp_servers(config).items():
        if definition["_plugin"] == plugin.name:
            rows.append(f"  MCP {name}: " + ("on" if plugins.mcp_on(name, definition, config.get("mcp_enabled", {}))
                        else "off"))
            if definition.get("eirene_adapter"):
                rows.append(f"  MCP packages and caches: {plugins.paths.home() / 'plugin-data' / plugin.name / 'mcp'}")
    if provider is not None and not (provider.supports_tools or getattr(provider, "owns_context", False)):
        rows.append("  Provider supports text only: executable workflows and MCP need a tool-capable provider")
    if plugin.name in {"eirene-skills", "skills"}:
        rows.append("  Skills have their own Python, Node.js, LibreOffice and Poppler prerequisites; each SKILL.md lists them")
        for tool in ("python3" if os.name != "nt" else "python", "node", "soffice", "pdftoppm"):
            found = shutil.which(tool) or (tool == "soffice" and shutil.which("libreoffice"))
            rows.append(f"  {tool}: {'found' if found else 'missing on PATH'}")
    if plugin.name == "playwright":
        rows.append("  Browser binaries/system libraries must be installed; the MCP browser-install tool can install supported binaries")
    if plugin.name == "serena":
        rows.append("  Serena selects Python 3.13 and the current project; language-server prerequisites vary by language")
    if os.name == "nt" and plugin.name == "superpowers":
        rows.append("  Startup hook needs Git Bash (its .cmd wrapper selects it)")
    rows.extend("  Compatibility: " + warning for warning in plugin.warnings)
    return "\n".join(rows)
