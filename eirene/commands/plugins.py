"""/plugins: a tabbed menu, plus typed commands compatible with Claude Code's /plugin."""

from __future__ import annotations

import asyncio
import json

from ..core import marketplace, paths, plugin_stats, plugins
from ..core import plugin_install
from ..core.plugin_install import export_skills, install, uninstall
from ..core.plugin_catalog import BUNDLES
from ..ui import art
from . import register


USAGE = ("usage: /plugins install <name@marketplace or repository> | update [name] | uninstall/enable/disable <name> | list | browse\n"
         "  | marketplace add <source> | marketplace list | marketplace update [name] | marketplace remove <name>\n"
         "  | doctor [name] | inspect/trust/untrust/refresh <name>")
MARKETPLACE_USAGE = ("usage: /plugin marketplace add <owner/repo, git URL, or local folder> | list | "
                     "update [name] | remove <name>")
INSTALLED_TAB, MARKETPLACE_TAB, STATS_TAB = range(3)
ALIASES = {"remove": "uninstall", "rm": "uninstall", "market": "marketplace"}


def _count(catalog) -> str:
    return f"{len(catalog.plugins)} plugin" + ("" if len(catalog.plugins) == 1 else "s")


async def _with_progress(app, title: str, work):
    """Run ``work(report)`` on a thread, with a live bar where there is an interface."""
    bar = None
    if hasattr(app, "transcript") and hasattr(app, "push"):
        from ..ui.install_progress import InstallProgress
        bar = await app.push(InstallProgress(title))
    else:
        app.say(title + "…")
    loop = asyncio.get_running_loop()

    def report(stage: str, fraction: float) -> None:
        if bar is not None:
            loop.call_soon_threadsafe(bar.advance, stage, fraction)

    try:
        return await asyncio.to_thread(work, report)
    finally:
        if bar is not None:
            await bar.remove()


def find_plugin(wanted: str, found=None):
    """An installed plugin by name, catalog shortcut, or name@marketplace."""
    name, at, market = wanted.partition("@")
    for plugin in plugins.discover() if found is None else found:
        if name.casefold() in {plugin.name.casefold(), plugin.catalog_shortcut.casefold()} \
                and (not at or plugin.marketplace.casefold() == market.casefold()):
            return plugin
    return None


@register("plugins", "manage plugins; marketplace add <source> | install <name@marketplace, owner/repo[/path], or local directory>")
async def run(app, args: str) -> None:
    if args.strip():
        action, _, source = args.strip().partition(" ")
        action = ALIASES.get(action, action)
        source = source.strip()
        if action == "marketplace":
            await _marketplace(app, source)
            return
        if action == "update":
            await _update(app, source)
            return
        if action == "list":
            found = plugins.discover()
            app.say("\n".join(f"{p.name}{'@' + p.marketplace if p.marketplace else ''}: "
                              f"{plugin_stats.state(p.name, app.config)}"
                              for p in found) or "no plugins installed")
            return
        if action == "browse":
            app.say("Portable bundles:\n" + "\n".join(
                f"{name} — {purpose}: /plugins install {name}" for name, _, purpose in BUNDLES)
                + "".join(f"\n{entry['name']}@{catalog.name} — {entry.get('description', '')}"
                          for catalog in marketplace.known() for entry in catalog.plugins)
                + "\nUse /plugins inspect <installed-name> for compatibility and dependencies; "
                "enable hooks with /plugins trust <installed-name>; enable MCP servers with /mcp.")
            return
        if action == "doctor":
            from ..core.plugin_health import report
            found = plugins.discover()
            if source:
                wanted = find_plugin(source, found)
                found = [wanted] if wanted else []
            if not found:
                app.say(f"plugin not found: {source}" if source else "no plugins installed")
                return
            provider = getattr(getattr(app, "agent", None), "provider", None)
            app.say("\n\n".join(report(p, app.config, provider=provider) for p in found))
            manager = getattr(getattr(app, "agent", None), "mcp", None)
            if manager and manager.errors:
                app.say("MCP startup errors:\n" + "\n".join(manager.errors))
            return
        if action in ("inspect", "trust", "untrust", "refresh", "uninstall", "enable", "disable"):
            plugin = find_plugin(source) if source else None
            if plugin is None:
                app.say(f"plugin not found: {source}")
                return
            if action == "inspect":
                app.say(describe(plugin, app.config))
                return
            if getattr(app, "turn", None) and not app.turn.done():
                app.say("finish or stop the current turn before changing executable plugins")
                return
            if action == "uninstall":
                await _uninstall(app, plugin)
                return
            if action in ("enable", "disable"):
                app.config.set_plugin(plugin.name, action == "enable")
                app._save_config()
                app.agent.reload_skills()
                app.say(f"{plugin.name} {action}d; takes effect on the next turn")
                return
            trust = dict(app.config.get("plugin_trust", {}))
            if action == "trust":
                app.say(describe(plugin, app.config))
                choice = await app.ask_choice(
                    f"Trust {plugin.name}? All of it will work.",
                    [("no", "cancel", "keep the whole plugin off"),
                     ("yes", "trust plugin", "its commands, skills, agents, hooks and MCP servers, "
                                             "under Eirene's configured execution policy")])
                if choice != "yes":
                    return
                trust[plugin.name] = True
                # All of it means all of it, including a server turned off earlier.
                enabled = dict(app.config.get("mcp_enabled", {}))
                for name, definition in plugins.available_mcp_servers(app.config).items():
                    if definition["_plugin"] == plugin.name:
                        enabled.pop(name, None)
                app.config.set("mcp_enabled", enabled)
            else:
                trust.pop(plugin.name, None)
            if action == "refresh":
                from ..core.plugin_manifest import normalize
                index = plugin_install._read_index(plugin.path)
                entry = index.get("marketplace_entry")
                entry = entry if isinstance(entry, dict) else None
                manifest = normalize(plugin.path, plugin.name, entry)
                if entry:
                    manifest["marketplace"] = plugin.marketplace
                    manifest["marketplace_entry"] = entry
                # Updates still need to know the origin; a missing digest only adds a backup.
                for key in ("install_source", "skills_digest"):
                    if key in index:
                        manifest[key] = index[key]
                # Keep the installed identity and resources; rebuild the old skills-only index.
                manifest["name"] = plugin.name
                if plugin.catalog_shortcut:
                    manifest["catalog_shortcut"] = plugin.catalog_shortcut
                folder = paths.skills_dir() / plugin.name
                if manifest["skills"] and not folder.exists():
                    export_skills(plugin.name, plugin.path, manifest["skills"])
                if manifest["skills"]:
                    manifest["skills_exported"] = True
                temporary = plugin.path / ".plugin.json.tmp"
                temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
                temporary.replace(plugin.path / ".eirene-plugin.json")
                app.agent.reload_skills()
            app.config.set("plugin_trust", trust)
            app._save_config()
            app.agent.reload_skills()
            if action == "trust":
                state = "on now" if app.config.plugin_enabled(plugin.name) else \
                    f"trusted, but disabled: run /plugins enable {plugin.name}"
                app.say(f"{plugin.name} is {state}. Its commands and skills work right away; "
                        "hooks and MCP servers start with your next message.")
            elif action == "untrust":
                app.say(f"{plugin.name} is off: its commands, skills, agents, hooks and MCP servers no longer work.")
            else:
                app.say(f"{plugin.name}: refreshed, and it is off until you trust it again: /plugins trust {plugin.name}")
            return
        if action != "install" or not source:
            app.say(USAGE)
            return
        try:
            name, count = await _with_progress(
                app, f"Installing {source}", lambda report: install(source, progress=report))
        except (OSError, ValueError) as exc:
            app.say(f"install failed: {exc}")
            return
        app.agent.reload_skills()
        plugin = next(p for p in plugins.discover() if p.name == name)
        for warning in plugin.warnings:
            app.say(f"{name}: {warning}")
        if name == "omniroute" and any(d.get("eirene_provider") == "omniroute" for d in plugin.mcp_servers.values()):
            app.say("installed omniroute management MCP adapter for your existing gateway. OmniRoute is now "
                    "available in /connect. The adapter uses your /connect omniroute URL and key. "
                    "Management stays off until you trust it: /plugins trust omniroute.")
            return
        app.say(f"installed {name}: {count} skills. It stays off until you trust it: "
                f"/plugins inspect {name}, then /plugins trust {name}.")
        return
    await menu(app)


async def menu(app, tab: int = INSTALLED_TAB) -> None:
    """The /plugins picker: Tab moves between Installed, Marketplace and Stats."""
    selected = ""
    while True:
        found = plugins.discover()
        catalogs = marketplace.known()
        header, stats = plugin_stats.table(app.config, found)
        tabs = [("Installed", _installed_rows(app, found)),
                ("Marketplace", _marketplace_rows(found, catalogs)),
                ("Stats", stats, header)]
        tab, chosen = await app.ask_tabs("Plugins", tabs, tab=tab, selected=selected)
        if not chosen:
            return
        selected = chosen
        action, _, name = chosen.partition(":")
        turn = getattr(app, "turn", None)
        if turn and not turn.done():
            app.say("finish or stop the current turn before changing plugins")
            continue
        if action == "install":
            await run(app, "install " + name)
        elif action == "market-add":
            source = await app.ask_text("marketplace: owner/repo, git URL, or local folder")
            if source and source.strip():
                await _marketplace(app, "add " + source.strip())
        elif action == "market":
            catalog = next((item for item in catalogs if item.name == name), None)
            operation = await app.ask_choice(name, [
                *(_catalog_rows(found, catalog) if catalog else []),
                ("update", "Update marketplace", "", "download the catalog again; installed plugins stay as they are"),
                ("remove", "Remove marketplace", "", "forget this catalog; installed plugins stay installed"),
            ], right_hint=True)
            kind, _, value = (operation or "").partition(":")
            if kind == "install":
                await run(app, "install " + value)
            elif kind == "installed":
                await _manage(app, next((p for p in found if p.name == value), None))
            elif operation:
                await _marketplace(app, f"{operation} {name}")
        elif action == "installed":
            await _manage(app, next((p for p in found if p.name == name), None))


async def _manage(app, plugin) -> None:
    if plugin is None:
        return
    name = plugin.name
    enabled = app.config.plugin_enabled(name)
    trusted = app.config.plugin_trusted(name)
    operation = await app.ask_choice(name, [
        (("untrust", "Revoke trust", "turns the whole plugin off") if trusted else
         ("trust", "Trust", "turns on its commands, skills, agents, hooks and MCP servers")),
        ("toggle", "Disable" if enabled else "Enable", "keeps its trust; takes effect on the next turn"),
        ("inspect", "Inspect", "commands, dependencies, and compatibility"),
        ("doctor", "Check prerequisites", "read-only diagnostics"),
        ("update", "Update", "download it again; if it changed, trust it again"),
        ("uninstall", "Uninstall", "delete this plugin and its copied skills"),
    ])
    if operation == "toggle":
        await run(app, ("disable " if enabled else "enable ") + name)
    elif operation:
        await run(app, operation + " " + name)


def _installed_rows(app, found) -> list[tuple]:
    rows = []
    for plugin in found:
        state = plugin_stats.state(plugin.name, app.config)
        origin = f"{plugin.marketplace} · " if plugin.marketplace else ""
        rows.append(("installed:" + plugin.name, plugin.name, origin + state, plugin.description))
    return rows


def _listing_row(found, slug, listing, install, purpose) -> tuple:
    installed = next((p for p in found if slug in {p.name, p.catalog_shortcut}), None)
    if installed:
        return ("installed:" + installed.name, slug, f"{listing} · installed", installed.description or purpose)
    return ("install:" + install, slug, f"{listing} · available", purpose)


def _catalog_rows(found, catalog) -> list[tuple]:
    return [_listing_row(found, entry["name"], catalog.name, f"{entry['name']}@{catalog.name}",
                         str(entry.get("description") or "")) for entry in catalog.plugins]


def _marketplace_rows(found, catalogs) -> list[tuple]:
    """Add a catalog, the added catalogs, what they list, then Eirene's own suggestions."""
    rows = [("market-add:", "+ Add marketplace", "", "owner/repo, git URL, or local folder")]
    for catalog in catalogs:
        rows.append(("market:" + catalog.name, f"{art.icon('dir')} {catalog.name}",
                     "unreadable" if catalog.error else _count(catalog),
                     catalog.error or catalog.description or catalog.source))
    for catalog in catalogs:
        rows += _catalog_rows(found, catalog)
    rows += [_listing_row(found, slug, "eirene", slug, f"{purpose} · {source}") for slug, source, purpose in BUNDLES]
    return rows


async def _marketplace(app, args: str) -> None:
    action, _, value = args.strip().partition(" ")
    action, value = {"rm": "remove"}.get(action, action), value.strip()
    if not action:
        await menu(app, MARKETPLACE_TAB)
        return
    try:
        if action == "list":
            app.say("\n".join(f"{c.name} ({_count(c)}) — {c.error or c.source}"
                              for c in marketplace.known())
                    or "no marketplaces added; use /plugin marketplace add <owner/repo>")
        elif action == "add" and value:
            catalog = await _with_progress(
                app, f"Adding marketplace {value}", lambda report: marketplace.add(value, report))
            example = f" Install one with /plugin install {catalog.plugins[0]['name']}@{catalog.name}." \
                if catalog.plugins else ""
            app.say(f"added marketplace {catalog.name}: {_count(catalog)}, none installed yet.{example}")
        elif action == "update":
            updated = await _with_progress(
                app, f"Updating marketplace {value}" if value else "Updating marketplaces",
                lambda report: marketplace.update(value, report))
            app.say("\n".join(f"updated {c.name}: {_count(c)}" for c in updated)
                    or "no marketplaces added")
        elif action == "remove" and value:
            marketplace.remove(value)
            app.say(f"removed marketplace {value}; plugins installed from it stay installed")
        else:
            app.say(MARKETPLACE_USAGE)
    except (OSError, ValueError) as exc:
        app.say(f"marketplace {action} failed: {exc}")


async def _update(app, wanted: str) -> None:
    turn = getattr(app, "turn", None)
    if turn and not turn.done():
        app.say("finish or stop the current turn before changing plugins")
        return
    found = plugins.discover()
    if wanted:
        plugin = find_plugin(wanted, found)
        if plugin is None:
            app.say(f"plugin not found: {wanted}")
            return
        found = [plugin]
    if not found:
        app.say("no plugins installed")
        return
    refreshed: set[str] = set()
    for plugin in found:
        try:
            result = await _with_progress(
                app, f"Updating {plugin.name}",
                lambda report, plugin=plugin: plugin_install.update(plugin, refreshed=refreshed, progress=report))
        except (OSError, ValueError) as exc:
            app.say(f"{plugin.name}: update failed: {exc}")
            continue
        if not result.changed:
            app.say(f"{plugin.name} is already up to date")
            continue
        revoked = _revoke_trust(app, plugin)
        app._save_config()
        app.agent.reload_skills()
        notes = [f"updated {plugin.name}: {result.skills} skills."]
        if revoked:
            notes.append(f"Its code changed, so the whole plugin is off until you trust it again: "
                         f"/plugins inspect {plugin.name}, then /plugins trust {plugin.name}.")
        if result.backup:
            notes.append(f"Its previous skills folder may have had your edits; saved a copy at {result.backup}.")
        app.say(" ".join(notes))


def _revoke_trust(app, plugin) -> bool:
    """Trust covered the code that was reviewed, so new code starts off."""
    trust = dict(app.config.get("plugin_trust", {}))
    if trust.pop(plugin.name, None) is None:
        return False
    app.config.set("plugin_trust", trust)
    return True


async def _uninstall(app, plugin) -> None:
    choice = await app.ask_choice(f"Uninstall {plugin.name}?", [
        ("no", "cancel", "keep this plugin"),
        ("yes", "uninstall", f"delete {plugin.path} and its copied skills, including any edits to them"),
    ])
    if choice != "yes":
        return
    owned = [name for name, definition in plugins.available_mcp_servers(app.config).items()
             if definition["_plugin"] == plugin.name]
    try:
        uninstall(plugin)
    except (OSError, ValueError) as exc:
        app.say(f"uninstall failed: {exc}")
        return
    # A later reinstall starts untrusted, as any fresh install does.
    for key, keep in (("plugin_trust", lambda name: name != plugin.name),
                      ("plugins", lambda name: name != plugin.name),
                      ("skills", lambda name: not name.startswith(plugin.name + ":")),
                      ("mcp_enabled", lambda name: name not in owned)):
        app.config.set(key, {name: value for name, value in dict(app.config.get(key, {})).items() if keep(name)})
    app._save_config()
    app.agent.reload_skills()
    app.say(f"uninstalled {plugin.name}; takes effect on the next turn")


def describe(plugin, config) -> str:
    from .plugin_commands import commands
    names = ["/" + (c.name.split(":", 1)[1] if c.hidden else c.name)
             for c in commands(config) if c.name.startswith(plugin.name + ":")]
    rows = [f"{plugin.name}: {plugin.description}", f"Directory: {plugin.path}",
            f"Trust: {'trusted' if config.plugin_trusted(plugin.name) else 'not trusted; nothing below runs until /plugins trust ' + plugin.name}",
            "Commands: " + (", ".join(names) or "none")]
    for event, hooks in plugin.lifecycle.items():
        rows.extend(f"{event}: {hook['command']}" for hook in hooks)
    if plugin.mcp_servers:
        rows.append("MCP servers start with trust; turn one off with /mcp")
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
        rows.append("Requires a separately installed OmniRoute executable and running gateway. Management uses the gateway's data directory; set EIRENE_OMNIROUTE_DATA_DIR before installing for custom DATA_DIR. See docs/providers/omniroute.md.")
    return "\n".join(rows)
