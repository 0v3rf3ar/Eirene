"""/plugins"""

from __future__ import annotations

import asyncio
import json

from ..core import plugins
from ..core.plugin_install import install
from ..core.plugin_catalog import BUNDLES
from . import register


@register("plugins", "manage plugins; browse | install <name, owner/repo[/path], or local directory>")
async def run(app, args: str) -> None:
    if args.strip():
        action, _, source = args.strip().partition(" ")
        source = source.strip()
        if action == "browse":
            app.say("Portable bundles:\n" + "\n".join(
                f"{name} — {purpose}: /plugins install {name}" for name, _, purpose in BUNDLES)
                + "\nUse /plugins inspect <installed-name> for compatibility and dependencies; "
                "enable executable components with /plugins trust <installed-name>.")
            return
        if action in ("inspect", "trust", "untrust", "refresh"):
            plugin = next((p for p in plugins.discover() if p.name == source), None)
            if plugin is None:
                app.say(f"plugin not found: {source}")
                return
            if action == "inspect":
                app.say(describe(plugin, app.config))
                return
            if getattr(app, "turn", None) and not app.turn.done():
                app.say("finish or stop the current turn before changing executable plugins")
                return
            trust = dict(app.config.get("plugin_trust", {}))
            if action == "trust":
                app.say(describe(plugin, app.config))
                choice = await app.ask_choice(
                    f"Allow {plugin.name}'s hook commands and MCP servers to execute?",
                    [("no", "cancel", "keep executable components disabled"),
                     ("yes", "trust plugin", "run with Eirene's configured execution policy")])
                if choice != "yes":
                    return
                trust[plugin.name] = True
            else:
                trust.pop(plugin.name, None)
            if action == "refresh":
                from ..core.plugin_manifest import normalize
                manifest = normalize(plugin.path, plugin.name)
                # Keep the installed identity and resources; rebuild the old skills-only index.
                manifest["name"] = plugin.name
                temporary = plugin.path / ".plugin.json.tmp"
                temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                temporary.replace(plugin.path / ".eirene-plugin.json")
                app.agent.reload_skills()
            app.config.set("plugin_trust", trust)
            app._save_config()
            app.say(f"{plugin.name}: {action} applied; takes effect on the next turn")
            return
        if action != "install" or not source:
            app.say("usage: /plugins install <repository> | browse | inspect/trust/untrust/refresh <name>")
            return
        app.say("installing plugin bundle…")
        try:
            name, count = await asyncio.to_thread(install, source.strip())
        except (OSError, ValueError) as exc:
            app.say(f"install failed: {exc}")
            return
        app.agent.reload_skills()
        plugin = next(p for p in plugins.discover() if p.name == name)
        for warning in plugin.warnings:
            app.say(f"{name}: {warning}")
        app.say(f"installed {name}: {count} skills; slash commands are available now. "
                f"Use /plugins inspect {name} for compatibility details."
                + (f" Enable executable components with /plugins trust {name}."
                   if any(plugin.lifecycle.values()) or plugin.mcp_servers else ""))
        return
    found = plugins.discover()
    if not found:
        app.say(f"no plugins - add <name>/plugin.json under {plugins.paths.plugins_dir()}")
        return
    while True:
        options = []
        for plugin in found:
            enabled = app.config.plugin_enabled(plugin.name)
            details = []
            if plugin.skills:
                details.append(f"{len(plugin.skills)} skills")
            details.append(f"{len(plugin.commands)} commands")
            if any(plugin.lifecycle.values()):
                details.append("hooks trusted" if plugins.executable_enabled(plugin, app.config) else "hooks need trust")
            if plugin.mcp_servers:
                details.append(f"{len(plugin.mcp_servers)} MCP servers")
            options.append((plugin.name, f"{'on' if enabled else 'off'}  {plugin.name}",
                            ", ".join(details) or plugin.description))
        options.append(("", "done", ""))
        chosen = await app.ask_choice("toggle a plugin", options)
        if not chosen:
            break
        enabled = not app.config.plugin_enabled(chosen)
        app.config.set_plugin(chosen, enabled)
        app._save_config()
        app.agent.reload_skills()
        app.say(f"{chosen} {'enabled' if enabled else 'disabled'}; takes effect on the next turn")


def describe(plugin, config) -> str:
    from .plugin_commands import commands
    names = ["/" + c.name for c in commands(config) if c.name.startswith(plugin.name + ":")]
    rows = [f"{plugin.name}: {plugin.description}", f"Directory: {plugin.path}",
            f"Executable components: {'trusted' if plugins.executable_enabled(plugin, config) else 'disabled until trusted'}",
            "Commands: " + (", ".join(names) or "none")]
    for event, hooks in plugin.lifecycle.items():
        rows.extend(f"{event}: {hook['command']}" for hook in hooks)
    for name, definition in plugin.mcp_servers.items():
        rows.append(f"MCP {name}: {definition.get('command', definition.get('url', ''))}")
    rows.extend("Compatibility: " + warning for warning in plugin.warnings)
    if plugin.name == "ponytail":
        rows.append("Requires node on PATH. Portable activation and mode switches run in Eirene; native statusline and SubagentStart are not emulated.")
    return "\n".join(rows)
