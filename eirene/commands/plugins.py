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
                "enable hooks with /plugins trust <installed-name>; enable MCP servers with /mcp.")
            return
        if action == "doctor":
            from ..core.plugin_health import report
            found = [p for p in plugins.discover() if not source or p.name == source or p.catalog_shortcut == source]
            if not found:
                app.say(f"plugin not found: {source}" if source else "no plugins installed")
                return
            provider = getattr(getattr(app, "agent", None), "provider", None)
            app.say("\n\n".join(report(p, app.config, provider=provider) for p in found))
            manager = getattr(getattr(app, "agent", None), "mcp", None)
            if manager and manager.errors:
                app.say("MCP startup errors:\n" + "\n".join(manager.errors))
            return
        if action in ("inspect", "trust", "untrust", "refresh"):
            plugin = next((p for p in plugins.discover()
                           if source.casefold() in {p.name.casefold(), p.catalog_shortcut.casefold()}), None)
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
                    f"Allow {plugin.name}'s hook commands to execute?",
                    [("no", "cancel", "keep hooks disabled"),
                     ("yes", "trust plugin", "run with Eirene's configured execution policy")])
                if choice != "yes":
                    return
                trust[plugin.name] = True
            else:
                trust.pop(plugin.name, None)
                enabled = dict(app.config.get("mcp_enabled", {}))
                for name, definition in plugins.available_mcp_servers(app.config).items():
                    if definition["_plugin"] == plugin.name:
                        enabled[name] = False
                app.config.set("mcp_enabled", enabled)
            if action == "refresh":
                from ..core.plugin_manifest import normalize
                manifest = normalize(plugin.path, plugin.name)
                # Keep the installed identity and resources; rebuild the old skills-only index.
                manifest["name"] = plugin.name
                if plugin.catalog_shortcut:
                    manifest["catalog_shortcut"] = plugin.catalog_shortcut
                temporary = plugin.path / ".plugin.json.tmp"
                temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                temporary.replace(plugin.path / ".eirene-plugin.json")
                app.agent.reload_skills()
            app.config.set("plugin_trust", trust)
            app._save_config()
            app.say(f"{plugin.name}: {action} applied; takes effect on the next turn")
            return
        if action != "install" or not source:
            app.say("usage: /plugins install <repository> | browse | doctor [name] | inspect/trust/untrust/refresh <name>")
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
        if name == "omniroute" and any(d.get("eirene_provider") == "omniroute" for d in plugin.mcp_servers.values()):
            app.say("installed omniroute management MCP adapter for your existing gateway. "
                    "OmniRoute is now available in /connect. Use /mcp to enable management manually. "
                    "The adapter uses your /connect omniroute URL and key.")
            return
        app.say(f"installed {name}: {count} skills; slash commands are available now. "
                f"Use /plugins inspect {name} for compatibility details."
                + (f" Enable hooks with /plugins trust {name}."
                   if any(plugin.lifecycle.values()) else "")
                + (" Use /mcp to enable its MCP servers." if plugin.mcp_servers else ""))
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
            if plugin.agents:
                details.append(f"{len(plugin.agents)} specialist profiles")
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
            f"Hook execution: {'trusted' if plugins.executable_enabled(plugin, config) else 'disabled until trusted'}",
            "Commands: " + (", ".join(names) or "none")]
    for event, hooks in plugin.lifecycle.items():
        rows.extend(f"{event}: {hook['command']}" for hook in hooks)
    if plugin.mcp_servers:
        rows.append("MCP execution: enable or disable each server manually with /mcp")
    for name, definition in plugin.mcp_servers.items():
        rows.append(f"MCP {name}: {definition.get('command', definition.get('url', ''))}")
        if definition.get("network") is True:
            rows.append(f"MCP {name}: requests network access when enabled")
        if plugin.name == "omniroute" and definition.get("eirene_provider") == "omniroute":
            rows.append(f"MCP {name}: uses the saved /connect omniroute URL and key unless overridden in plugin.json")
        if definition.get("write_paths"):
            rows.append(f"MCP {name} writable paths: {definition['write_paths']}")
    rows.extend("Compatibility: " + warning for warning in plugin.warnings)
    from ..core.plugin_health import report
    rows.append("Diagnostics:\n" + report(plugin, config))
    if plugin.name == "ponytail":
        rows.append("Requires node on PATH. Portable activation and mode switches run in Eirene; native statusline and SubagentStart are not emulated.")
    if plugin.name == "omniroute":
        rows.append("Requires a separately installed OmniRoute executable and running gateway. Management uses the gateway's data directory; set EIRENE_OMNIROUTE_DATA_DIR before installing for custom DATA_DIR. See docs/omniroute.md.")
    return "\n".join(rows)
