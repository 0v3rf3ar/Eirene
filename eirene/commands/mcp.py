"""/mcp — explicit per-server execution grants."""
from __future__ import annotations

from ..core import plugins
from . import register


@register('mcp', 'enable or disable available MCP servers')
async def run(app, args: str) -> None:
    if getattr(app, 'turn', None) and not app.turn.done():
        app.say('finish or stop the current turn before changing MCP servers', 'warn')
        return
    selected = ''
    while True:
        available = plugins.available_mcp_servers(app.config)
        if not available:
            app.say('no MCP servers available; install a plugin with /plugins install <name>')
            return
        enabled = dict(app.config.get('mcp_enabled', {}))
        options = []
        for name, definition in available.items():
            active = enabled.get(name) is True and definition['_plugin_enabled']
            owner = definition['_plugin']
            label = name.replace(owner + '__', owner + ' / ', 1) if owner else name
            command = definition.get('command', [])
            command = ' '.join(command) if isinstance(command, list) else str(command)
            detail = command
            if definition.get('network') is True:
                detail += ' · network access'
            if definition.get('write_paths'):
                detail += ' · writes: ' + ', '.join(definition['write_paths'])
            if definition.get('eirene_provider') == 'omniroute':
                detail += ' · uses your saved OmniRoute URL/key'
            if not definition['_plugin_enabled']:
                detail += ' · plugin disabled'
            options.append((name, f"{'on' if active else 'off'}  {label}", detail))
        options.append(('', 'done', ''))
        chosen = await app.ask_choice('MCP servers — select to enable or disable', options, selected=selected)
        if not chosen:
            return
        if chosen not in available:
            continue
        selected = chosen
        definition = available[chosen]
        if not definition['_plugin_enabled']:
            app.say('enable this plugin with /plugins before enabling its MCP server', 'warn')
            continue
        active = enabled.get(chosen) is not True
        enabled[chosen] = active
        app.config.set('mcp_enabled', enabled)
        app._save_config()
        # Stop existing stdio processes before returning control to the user.
        manager = getattr(getattr(app, 'agent', None), 'mcp', None)
        if manager is not None:
            await manager.close()
        app.say(f"{chosen}: {'enabled' if active else 'disabled'}; takes effect on the next normal turn")
