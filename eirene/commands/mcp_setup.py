"""Guided MCP setup and connection diagnostics."""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from ..core import plugins
from ..core.errors import CommandError, ToolError
from ..core.mcp_auth import MCPSecrets
from ..core.mcp_config import import_json, prepare_local, transport, validate_url
from ..core.mcp_import import ImportCancelled, resolve_definition


async def stop_connections(app):
    manager = getattr(getattr(app, 'agent', None), 'mcp', None)
    if manager is not None:
        await manager.close()
    provider = getattr(getattr(app, 'agent', None), 'provider', None)
    reset = getattr(provider, 'reset_thread', None)
    if reset:
        reset()


async def check_connection(app, name: str, definition: dict, *, interactive=True) -> bool:
    from ..core.mcp_remote import make_client
    from ..core.permissions import isolation, isolate_network
    if getattr(getattr(getattr(app, 'agent', None), 'mode', None), 'value', '') == 'plan':
        app.say('Switch to manual or auto mode before connecting MCP servers.', 'warn')
        return False
    if not definition.get('_plugin_enabled', True):
        app.say('Enable the owning plugin with /plugins first.', 'warn')
        return False
    prepared = {**definition, '_isolation': isolation(app.config),
                '_isolate_network': isolate_network(app.config) and definition.get('network') is not True}
    root = app.sandbox.root
    client = None
    app.say(f'Connecting to {name}… Press Esc to cancel.')
    try:
        client = make_client(name, prepared, root, interactive=interactive, say=app.say)
        tools = await client.connect()
        app.say(f'{name}: connected · {len(tools)} tools available')
        if not tools:
            app.say('This server advertises no tools; Eirene currently uses MCP tools only.', 'warn')
        return True
    except (ToolError, ValueError, OSError) as exc:
        app.say(f'{name}: {exc}', 'warn')
        return False
    finally:
        if client:
            await client.close()


async def _authentication(app, name, definition):
    choice = await app.ask_choice('Authentication', [
        ('oauth', 'Sign in with browser', 'OAuth; login and refresh handled by Eirene'),
        ('oauth-client', 'Registered OAuth application', 'client ID, secret, and registered localhost callback'),
        ('token', 'API token', 'paste a bearer token securely'),
        ('headers', 'Custom headers', 'API keys or other authentication headers'),
        ('none', 'No authentication', 'public or local server'),
    ], selected=definition.get('auth', 'oauth'), footer='Esc cancel setup')
    if not choice:
        return None
    definition['auth'] = 'oauth' if choice in ('oauth', 'oauth-client') else 'none'
    headers = {}
    if choice == 'oauth-client':
        client_id = await app.ask_text('OAuth client ID')
        if not client_id:
            return None
        client_secret = await app.ask_text('OAuth client secret (hidden)', secret=True)
        if not client_secret:
            return None
        redirect_uri = await app.ask_text('Registered localhost callback URL, e.g. http://127.0.0.1:8765/callback')
        if not redirect_uri:
            return None
        definition['oauth'] = {**definition.get('oauth', {}), 'client_id': client_id.strip(),
                               'client_secret': client_secret.strip(), 'redirect_uri': redirect_uri.strip()}
    elif choice == 'token':
        token = await app.ask_text('API token (hidden)', secret=True)
        if not token:
            return None
        headers['Authorization'] = 'Bearer ' + token.strip()
    elif choice == 'headers':
        while True:
            value = await app.ask_text('Headers as JSON, e.g. {"X-API-Key":"…"} (hidden)', secret=True)
            if value is None:
                return None
            try:
                headers = json.loads(value)
                if not isinstance(headers, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in headers.items()):
                    raise ValueError()
                break
            except ValueError:
                app.say('Enter a JSON object with header names and string values.', 'warn')
    return headers


async def _save(app, name, definition, headers=None, *, action=None):
    available = plugins.available_mcp_servers(app.config)
    if name in available:
        if available[name]['_plugin']:
            app.say('That name belongs to a plugin. Choose a different server name.', 'warn')
            return
        replace = await app.ask_choice(f'Replace {name}?', [
            ('no', 'Keep existing server', ''), ('replace', 'Replace server', 'old activation will be cleared')])
        if replace != 'replace':
            return
    if action is None:
        action = await app.ask_choice(f'{name} — ready to connect', [
            ('connect', 'Connect and enable', 'test the connection and discover its tools',
             ('Network access. ' if definition.get('network') else '')
             + ' '.join(f"{field}: {', '.join(definition.get(field, []))}." for field in ('read_paths', 'write_paths') if definition.get(field))),
            ('save', 'Save disabled', 'connect later with /mcp test ' + name),
        ], footer='Esc cancel setup')
    if action not in ('connect', 'save'):
        return
    remote = transport(definition) != 'stdio'
    if remote:
        storage = MCPSecrets(name, definition['url'])
        previous_auth = storage.read()
        # Keep imported or entered header credentials out of config.json.
        auth = definition.get('auth', 'auto')
        oauth = definition.pop('oauth', {})
        changes = dict(headers=headers if headers is not None else definition.pop('headers', {}), auth=auth, oauth=oauth)
        previous_definition = available.get(name, {})
        if previous_auth and (previous_auth.get('auth', 'auto') != auth
                or previous_auth.get('oauth', {}) != oauth
                or previous_definition.get('scope') != definition.get('scope')
                or previous_definition.get('client_metadata_url') != definition.get('client_metadata_url')):
            changes.update(tokens=None, client=None, expires_at=None, oauth_metadata=None,
                           resource_metadata=None, auth_server_url=None)
        storage.update(**changes)
        definition.pop('headers', None)
    servers = dict(app.config.get('mcp_servers', {}))
    previous = servers.get(name)
    servers[name] = definition
    enabled = dict(app.config.get('mcp_enabled', {}))
    enabled[name] = False
    app.config.set('mcp_servers', servers)
    app.config.set('mcp_enabled', enabled)
    app._save_config()
    await stop_connections(app)
    if previous and previous.get('url') and previous['url'] != definition.get('url'):
        MCPSecrets(name, previous['url']).delete()
    if action == 'connect' and await check_connection(app, name, definition):
        enabled[name] = True
        app.config.set('mcp_enabled', enabled)
        app._save_config()
        app.say(f'{name}: enabled; ready for the next normal turn')
    else:
        app.say(f'{name}: saved disabled; use /mcp to enable or /mcp test {name} to retry')


async def add(app, args=''):
    parts = shlex.split(args)
    if len(parts) == 2:
        name, endpoint = parts
        definition = {'type': 'http', 'url': validate_url(endpoint), 'network': True}
        headers = await _authentication(app, name, definition)
        if headers is not None:
            await _save(app, name, definition, headers)
        return
    if len(parts) > 2:
        raise CommandError('usage: /mcp add [name] or /mcp import [path]')
    await import_servers(app, name=parts[0] if parts else '')


async def import_servers(app, path='', *, name=''):
    while True:
        value = path or await app.ask_text('Paste MCP JSON, or enter a JSON file path')
        if value is None:
            return
        try:
            if not value.lstrip('\ufeff \n\r\t').startswith(('{', '```')):
                candidate = Path(value.strip().strip('"').strip("'")).expanduser()
                candidate = (app.sandbox.root / candidate).resolve()
                if candidate.stat().st_size > 2 * 1024 * 1024:
                    raise ValueError('MCP JSON file is too large')
                value = candidate.read_text(encoding='utf-8-sig')
            try:
                servers = import_json(value, name=name)
            except ValueError as exc:
                if 'single server definition needs a name' not in str(exc):
                    raise
                name = await app.ask_text('Server name')
                if name is None:
                    return
                servers = import_json(value, name=name)
            break
        except (ValueError, OSError):
            app.say('Cannot read this MCP JSON. Paste a server configuration or choose an existing JSON/JSONC file.', 'warn')
            if path:
                return
    values = {}
    prepared = []
    for server_name, definition in servers.items():
        try:
            definition = await resolve_definition(definition, app.sandbox.root, app.ask_text,
                                                  app.ask_choice, values=values)
            if transport(definition) == 'stdio':
                definition['auto_setup'] = True
                try:
                    definition = prepare_local(server_name, definition)
                except ValueError as exc:
                    app.say(f'{server_name}: {exc}; the declaration can be saved disabled.', 'warn')
            prepared.append((server_name, definition))
        except ImportCancelled:
            return
        except ValueError as exc:
            app.say(f'{server_name}: {exc}', 'warn')
    action = None
    if len(prepared) > 1:
        action = await app.ask_choice(f'Import {len(prepared)} MCP servers', [
            ('connect', 'Connect and enable all', 'test each connection before enabling', ', '.join(name for name, _ in prepared)),
            ('save', 'Save all disabled', 'connect later from /mcp'),
        ], footer='Esc cancel import')
        if not action:
            return
    for server_name, definition in prepared:
        await _save(app, server_name, definition, action=action)


async def manage(app, action, name):
    available = plugins.available_mcp_servers(app.config)
    definition = available.get(name)
    if definition is None:
        raise CommandError('unknown MCP server; open /mcp to see available names')
    if action == 'remove':
        if definition['_plugin']:
            raise CommandError('this server belongs to a plugin; manage it with /plugins')
        answer = await app.ask_choice(f'Remove {name}?', [
            ('no', 'Keep server', ''), ('remove', 'Remove server', 'also delete its saved credentials')])
        if answer != 'remove':
            return
        await stop_connections(app)
        servers = dict(app.config.get('mcp_servers', {}))
        servers.pop(name, None)
        enabled = dict(app.config.get('mcp_enabled', {}))
        enabled.pop(name, None)
        app.config.set('mcp_servers', servers)
        app.config.set('mcp_enabled', enabled)
        app._save_config()
        if definition.get('url'):
            MCPSecrets(name, definition['url']).delete()
        app.say(name + ': removed')
        return
    if action == 'login':
        if transport(definition) == 'stdio':
            raise CommandError('local servers manage their own login; use /mcp test ' + name)
        answer = await _authentication(app, name, definition)
        if answer is None:
            return
        store = MCPSecrets(name, definition['url'])
        store.update(headers=answer, auth=definition.get('auth', 'none'),
                     oauth=definition.pop('oauth', store.read().get('oauth', {})),
                     tokens=None, expires_at=None)
        if not definition['_plugin']:
            definition = {k: v for k, v in definition.items() if not k.startswith('_')}
            servers = dict(app.config.get('mcp_servers', {}))
            servers[name] = definition
            app.config.set('mcp_servers', servers)
            app._save_config()
        await stop_connections(app)
    await check_connection(app, name, definition)
