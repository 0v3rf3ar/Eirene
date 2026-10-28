"""/mcp — explicit per-server execution grants."""
from __future__ import annotations

from ..core import plugins
from ..core.errors import CommandError
from ..core.mcp_config import transport
from . import register


@register('mcp', 'add, connect, and manage MCP servers',
          '/mcp [add [name] [url] | import | test <name> | login <name> | remove <name>]')
async def run(app, args: str) -> None:
    if getattr(app, 'turn', None) and not app.turn.done():
        app.say('finish or stop the current turn before changing MCP servers', 'warn')
        return
    from .mcp_setup import add, import_servers, manage, stop_connections
    if args:
        action, _, rest = args.partition(' ')
        if action == 'add':
            await add(app, rest.strip())
        elif action == 'import':
            await import_servers(app, rest.strip())
        elif action in ('test', 'login', 'remove') and rest.strip():
            await manage(app, action, rest.strip())
        else:
            raise CommandError('usage: /mcp [add | import | test <name> | login <name> | remove <name>]')
        return
    selected = ''
    while True:
        available = plugins.available_mcp_servers(app.config)
        enabled = dict(app.config.get('mcp_enabled', {}))
        options = []
        for name, definition in available.items():
            active = enabled.get(name) is True and definition['_plugin_enabled']
            owner = definition['_plugin']
            label = name.replace(owner + '__', owner + ' / ', 1) if owner else name
            details = []
            try:
                kind = transport(definition)
                if kind != 'stdio':
                    details.append('HTTP' if kind == 'http' else 'SSE')
            except ValueError:
                details.append('invalid declaration; use Manage connection to remove it')
            if definition.get('network') is True:
                details.append('network access')
            if definition.get('write_paths'):
                details.append('writes: ' + ', '.join(definition['write_paths']))
            if definition.get('eirene_provider') == 'omniroute':
                details.append('uses your saved OmniRoute URL/key')
            if not definition['_plugin_enabled']:
                details.append('plugin disabled')
            state = 'on' if active else 'off'
            options.append((name, f'{label} ({state})', '', ' · '.join(details)))
        options.append((':add', 'Add MCP server…', '', 'paste MCP JSON or import a JSON file'))
        if available:
            options.append((':manage', 'Manage connection…', '', 'test, sign in, or remove a server'))
        chosen = await app.ask_choice('MCP servers — select to enable or disable', options,
                                      selected=selected, footer='Esc back to menu')
        if not chosen:
            return
        if chosen == ':add':
            await add(app)
            continue
        if chosen == ':manage':
            name = await app.ask_choice('Manage which server?', [
                (key, key, '') for key in available], footer='Esc back to MCP servers')
            if name not in available:
                continue
            action = await app.ask_choice(name, [
                ('test', 'Test connection', 'discover available tools'),
                ('login', 'Sign in / update authentication', 'browser, API token, or custom headers'),
                ('remove', 'Remove server', 'standalone connections only'),
            ], footer='Esc back to MCP servers')
            if action:
                await manage(app, action, name)
            continue
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
        await stop_connections(app)
        app.say(f"{chosen}: {'enabled' if active else 'disabled'}; takes effect on the next normal turn")
        from ..core.permissions import isolation
        from ..core.platforms import is_termux
        if active and is_termux() and isolation(app.config) == "none":
            app.say("Android has no Eirene sandbox: this server runs with your Termux "
                    "account's access", "warn")
