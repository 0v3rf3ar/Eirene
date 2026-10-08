"""Declarations and runtime bindings for an optional, externally managed gateway."""
from __future__ import annotations

import os
from pathlib import Path
import shutil

from .plugin_manifest import read_object


def data_directory() -> Path:
    configured = os.environ.get('EIRENE_OMNIROUTE_DATA_DIR')
    legacy = Path.home() / '.omniroute'
    if configured:
        return Path(configured).expanduser().resolve()
    if legacy.is_dir():
        return legacy
    if os.name == 'nt':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming') / 'omniroute'
    if os.environ.get('XDG_CONFIG_HOME'):
        return Path(os.environ['XDG_CONFIG_HOME']).expanduser().resolve() / 'omniroute'
    return legacy


def manifest() -> dict:
    data = str(data_directory())
    return {'name': 'omniroute',
            'description': 'Management MCP tools for your separately installed OmniRoute gateway. Requires OmniRoute on PATH, a running gateway, and plugin trust.',
            'mcpServers': {'gateway': {'command': 'omniroute', 'args': ['--mcp'],
                'eirene_provider': 'omniroute', 'network': True,
                'env': {'DATA_DIR': data}, 'write_paths': [data]}}}


def bind(definition: dict, config) -> dict:
    """Share the saved connection; explicit manifest environment overrides win."""
    result = dict(definition)
    env = dict(result.get('env', {}))
    url = config.base_url('omniroute') or 'http://localhost:20128/v1'
    env.setdefault('OMNIROUTE_BASE_URL', url.rstrip('/').removesuffix('/v1'))
    key = config.api_key('omniroute')
    if key:
        env.setdefault('OMNIROUTE_API_KEY', key)
    result['env'] = env
    if result.get('command') != ['omniroute', '--mcp']:
        return result
    executable = shutil.which('omniroute')
    if not executable:
        return result
    cli = Path(executable).resolve()
    reads = list(result.get('read_paths', []))
    reads.append(str(cli))
    # Global npm shims point into the package; expose its sibling dependencies too.
    for parent in list(cli.parents)[:5]:
        try:
            if read_object(parent / 'package.json').get('name') == 'omniroute':
                reads.append(str(parent.parent if parent.parent.name == 'node_modules' else parent))
                break
        except (OSError, ValueError):
            continue
    node = shutil.which('node')
    if node and cli.suffix in {'.js', '.mjs', '.cjs'}:
        node = str(Path(node).resolve())
        result['command'] = [node, str(cli), '--mcp']
        reads.append(str(Path(node).parent))
    else:
        result['command'] = [str(cli), '--mcp']
        if os.name == 'nt':
            reads.append(str(cli.parent))
    result['read_paths'] = list(dict.fromkeys(reads))
    return result
