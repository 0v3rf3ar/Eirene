"""/plugins"""

from __future__ import annotations

from ..core import plugins
from . import register


@register("plugins", "enable or disable local declarative plugins")
async def run(app, args: str) -> None:
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
        app.say(f"{chosen} {'enabled' if enabled else 'disabled'}; restart to reload tools")
