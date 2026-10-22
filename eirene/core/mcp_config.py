"""Normalize MCP declarations shared by the wizard, importer, and runtime."""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

from . import paths


def transport(definition: dict) -> str:
    kind = definition.get('type', definition.get('transport', ''))
    if kind in ('http', 'streamable-http', 'streamable_http', 'streamablehttp', 'remote'):
        return 'http'
    if kind == 'sse':
        return 'sse'
    if kind in ('', 'stdio', 'local'):
        return 'http' if definition.get('url') or definition.get('serverUrl') else 'stdio'
    raise ValueError('supported MCP types: stdio, http, sse')


def validate_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('https', 'http') or not parsed.hostname:
        raise ValueError('enter a complete http:// or https:// MCP URL')
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError('put credentials in authentication settings, not in the URL')
    return value.strip()


def normalize(definition: dict) -> dict:
    result = dict(definition)
    kind = transport(result)
    result['type'] = kind
    result.pop('transport', None)
    if kind != 'stdio':
        result['url'] = validate_url(str(result.get('url') or result.get('serverUrl') or ''))
        result.pop('serverUrl', None)
        if not isinstance(result.get('headers', {}), dict):
            raise ValueError('MCP headers must be an object')
        oauth = result.get('oauth', {})
        auth = result.get('auth')
        if isinstance(auth, dict):
            oauth = {**auth, **oauth}
            auth = auth.get('type', 'oauth')
        if not isinstance(oauth, dict):
            raise ValueError('OAuth settings must be an object')
        aliases = {'clientId': 'client_id', 'clientSecret': 'client_secret',
                   'redirectUri': 'redirect_uri', 'authorizationParams': 'authorization_params'}
        oauth = {aliases.get(key, key): value for key, value in oauth.items() if key != 'type'}
        if oauth:
            result['oauth'] = oauth
        result['auth'] = auth or ('oauth' if oauth else 'none' if result.get('headers') else 'auto')
        if result['auth'] not in ('auto', 'none', 'oauth'):
            raise ValueError('remote authentication must be auto, none, or oauth; use headers for API keys')
        result.setdefault('network', True)
        return result
    command = result.get('command')
    command = [command] if isinstance(command, str) else command
    args = result.pop('args', [])
    if (not isinstance(command, list) or not command or not isinstance(args, list)
            or not command[0] or not all(isinstance(part, str) for part in command + args)):
        raise ValueError('stdio MCP needs an executable and separate arguments')
    result['command'] = command + args
    if not isinstance(result.get('env', {}), dict):
        raise ValueError('MCP environment must be an object')
    return result


def _json_text(value: str) -> str:
    """Accept copied fenced JSON/JSONC, preserving strings and their URLs."""
    value = value.lstrip('\ufeff').strip()
    if value.startswith('```') and value.endswith('```'):
        value = value.split('\n', 1)[1].rsplit('```', 1)[0]
    out, index, quoted = [], 0, False
    while index < len(value):
        char = value[index]
        if quoted:
            out.append(char)
            if char == '\\' and index + 1 < len(value):
                index += 1
                out.append(value[index])
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
            out.append(char)
        elif value[index:index + 2] == '//':
            end = value.find('\n', index)
            index = len(value) if end < 0 else end
            out.append('\n')
            continue
        elif value[index:index + 2] == '/*':
            end = value.find('*/', index + 2)
            if end < 0:
                raise ValueError('unterminated JSON comment')
            out.append(' ')
            index = end + 2
            continue
        elif char == ',' and value[index + 1:].lstrip().startswith(('}', ']')):
            pass
        else:
            out.append(char)
        index += 1
    # A comma followed by a comment needs a second pass after comment removal.
    text = ''.join(out)
    return _json_text(text) if text != value and re.search(r',\s*[}\]]', text) else text


def import_json(value: str, *, name: str = '') -> dict[str, dict]:
    body = json.loads(_json_text(value))
    if not isinstance(body, dict):
        raise ValueError('paste a JSON object containing mcpServers or mcp_servers')
    container = body.get('mcp', body)
    if not isinstance(container, dict):
        raise ValueError('MCP configuration must be an object')
    inputs = container.get('inputs', body.get('inputs', []))
    if not isinstance(inputs, list) or not all(isinstance(item, dict) and item.get('id') for item in inputs):
        raise ValueError('MCP inputs must be a list of named input objects')
    servers = container.get('mcpServers', container.get('mcp_servers', container.get('servers', container)))
    if not isinstance(servers, dict) or not servers:
        raise ValueError('no MCP servers found')
    if any(key in servers for key in ('command', 'url', 'serverUrl')):
        single_name = name or servers.get('name')
        if not single_name:
            raise ValueError('a single server definition needs a name; use /mcp add NAME')
        servers = {single_name: servers}
    if not isinstance(servers, dict) or not servers:
        raise ValueError('no MCP servers found')
    out = {}
    for name, definition in servers.items():
        if name in ('inputs', '$schema'):
            continue
        if not isinstance(definition, dict) or not valid_name(name):
            raise ValueError('each MCP server needs a name and a configuration object')
        transport(definition)
        # Resolve placeholders before validation: URLs in docs can contain
        # input expressions or hostname placeholders which aren't valid yet.
        out[name] = {**definition, '_inputs': inputs}
    if not out:
        raise ValueError('no MCP servers found')
    return out


def valid_name(name: str) -> bool:
    return (isinstance(name, str) and 0 < len(name) <= 128 and name not in ('.', '..')
            and not name.startswith(':') and not re.search(r'[/\\\x00-\x1f\x7f]', name))


def prepare_local(name: str, definition: dict) -> dict:
    """Give common launchers persistent caches without opening the whole home."""
    result = normalize(definition)
    if transport(result) != 'stdio':
        return result
    command = [str(Path(part).expanduser()) if part.startswith('~/') else part for part in result['command']]
    command = [part.split('=', 1)[0] + '=' + str(Path(part.split('=', 1)[1]).expanduser())
               if '=~/' in part else part for part in command]
    found = shutil.which(str(Path(command[0]).expanduser()))
    if not found and Path(command[0]).name in ('npx', 'node', 'uv', 'uvx', 'docker', 'java', 'python', 'python3'):
        found = shutil.which(Path(command[0]).name)
    if not found:
        raise ValueError(f'{command[0]} is not installed or is not on PATH; install its runtime first')
    command[0] = found
    result['command'] = command
    reads = list(result.get('read_paths', []))
    # nvm, fnm, pipx, and user-installed runtimes live outside system mounts.
    executable = Path(found).resolve()
    launch_directory = Path(found).absolute().parent
    runtime = executable.parent.parent if executable.suffix in ('.py', '.js') else executable.parent
    if not str(Path(found).absolute()).startswith(('/usr/', '/bin/', '/sbin/')):
        reads.append(str(launch_directory.parent if (launch_directory.parent / 'pyvenv.cfg').is_file() else launch_directory))
    if not str(executable).startswith(('/usr/', '/bin/', '/sbin/')):
        reads.append(str(runtime))
    node = shutil.which('node') if Path(found).name in ('npx', 'npx.cmd', 'npm') else None
    if node and not str(Path(node).resolve()).startswith('/usr/'):
        reads.append(str(Path(node).resolve().parent))
    if reads:
        result['read_paths'] = list(dict.fromkeys(reads))
    launcher = Path(found).stem
    directory = paths.home() / 'mcp-runtime' / name
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    runtime_home = directory / 'home'
    runtime_home.mkdir(exist_ok=True, mode=0o700)
    env = dict(result.get('env', {}))
    # Persist server-owned OAuth profiles, browser downloads, and configuration.
    # This is a private child-process home, not the user's entire home directory.
    env.setdefault('HOME', str(runtime_home))
    for key, child in (('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_DATA_HOME', 'data')):
        env.setdefault(key, str(runtime_home / child))
    result['_runtime_home'] = str(runtime_home)
    result['write_paths'] = list(dict.fromkeys([*result.get('write_paths', []), str(directory)]))
    result.setdefault('network', True)
    result.setdefault('startup_timeout', 120)
    if launcher in ('npx', 'npm', 'uv', 'uvx'):
        if launcher == 'npx' and not any(arg in ('-y', '--yes') for arg in command[1:]):
            command.insert(1, '-y')
        env.setdefault('npm_config_cache' if launcher in ('npx', 'npm') else 'UV_CACHE_DIR', str(directory))
        if launcher in ('uv', 'uvx'):
            env.setdefault('UV_PYTHON_INSTALL_DIR', str(directory / 'python'))
    # Local source/JAR launchers and explicitly supplied credential files.
    for part in [*command[1:], *env.values()]:
        if not isinstance(part, str) or '://' in part:
            continue
        candidate = Path(part.split('=', 1)[-1]).expanduser()
        if candidate.is_absolute() and candidate.is_file():
            reads.append(str(candidate))
    if launcher in ('docker', 'podman'):
        config = Path(env.get('DOCKER_CONFIG', os.environ.get('DOCKER_CONFIG', str(Path.home() / '.docker')))).expanduser()
        if config.is_dir():
            env['DOCKER_CONFIG'] = str(config)
            reads.append(str(config))
        endpoint = env.get('DOCKER_HOST', os.environ.get('DOCKER_HOST', ''))
        if endpoint:
            env['DOCKER_HOST'] = endpoint
        candidates = [Path(endpoint[7:])] if endpoint.startswith('unix://') else [
            Path('/var/run/docker.sock'), Path.home() / '.docker/run/docker.sock',
            Path(os.environ.get('XDG_RUNTIME_DIR', '/nonexistent')) / 'docker.sock']
        for candidate in candidates:
            if candidate.exists():
                result['write_paths'].append(str(candidate.resolve()))
                env.setdefault('DOCKER_HOST', 'unix://' + str(candidate.resolve()))
                break
    packages = ' '.join(command[1:])
    if 'kubernetes-mcp-server' in packages or launcher == 'kubernetes-mcp-server':
        configs = env.get('KUBECONFIG', os.environ.get('KUBECONFIG', str(Path.home() / '.kube/config')))
        existing = [str(Path(item).expanduser().resolve()) for item in configs.split(os.pathsep) if Path(item).expanduser().is_file()]
        if existing:
            env['KUBECONFIG'] = os.pathsep.join(existing)
            reads.extend(str(Path(item).parent) for item in existing)
    if any(package in packages for package in ('@playwright/mcp', 'chrome-devtools-mcp', 'server-puppeteer')):
        browser = next((path for binary in ('google-chrome', 'chromium', 'chromium-browser') if (path := shutil.which(binary))), None)
        if browser and '@playwright/mcp' in packages:
            env.setdefault('PLAYWRIGHT_MCP_EXECUTABLE_PATH', browser)
        if browser and 'chrome-devtools-mcp' in packages and not any(
                part.startswith(('--executablePath', '--executable-path', '--browserUrl', '--wsEndpoint', '--autoConnect'))
                for part in command):
            command.extend(['--executablePath', browser])
        if browser and 'server-puppeteer' in packages:
            env.setdefault('PUPPETEER_EXECUTABLE_PATH', browser)
        env.setdefault('PLAYWRIGHT_BROWSERS_PATH', str(directory / 'browsers'))
        env.setdefault('PUPPETEER_CACHE_DIR', str(directory / 'puppeteer'))
        if (result.get('_isolation') not in (None, 'none')
                or (not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'))):
            if '@playwright/mcp' in packages:
                env.setdefault('PLAYWRIGHT_MCP_HEADLESS', 'true')
            elif 'chrome-devtools-mcp' in packages and '--headless' not in command:
                command.append('--headless')
            elif 'server-puppeteer' in packages:
                env.setdefault('PUPPETEER_LAUNCH_OPTIONS', json.dumps({'headless': True}))
    result['env'] = env
    result['read_paths'] = list(dict.fromkeys(reads))
    result['write_paths'] = list(dict.fromkeys(result['write_paths']))
    return result
