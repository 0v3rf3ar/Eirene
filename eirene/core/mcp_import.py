"""Resolve portable MCP JSON inputs without executing editor commands or shells."""
from __future__ import annotations

import os
import re
from pathlib import Path

from .mcp_config import normalize

VARIABLE = re.compile(r'\$\{([^{}]+)\}')
PLACEHOLDER = re.compile(r'<<[^<>]+>>|<[^<>]+>|\bYOUR_[A-Z0-9_]+\b')


class ImportCancelled(Exception):
    pass


async def resolve_definition(definition, workspace, ask_text, ask_choice, *, values=None):
    inputs = {item['id']: item for item in definition.get('_inputs', [])}
    raw_env = definition.get('env', {})
    if not isinstance(raw_env, dict):
        raise ValueError('MCP environment must be an object')
    values = values if values is not None else {}
    busy, inherited = set(), {}

    async def prompt(key, description, *, secret=True, default=None):
        if key not in values:
            answer = await ask_text(description, secret=secret)
            if answer is None:
                raise ImportCancelled()
            answer = answer or default
            if not answer:
                raise ValueError(f'a value is required for {description}')
            values[key] = answer
        return values[key]

    async def variable(expression):
        name, _, fallback = expression.partition(':-')
        builtins = {'workspaceFolder': str(workspace), 'workspaceFolderBasename': Path(workspace).name,
                    'userHome': str(Path.home())}
        if name in builtins:
            return builtins[name]
        if name.startswith('command:'):
            raise ValueError('This JSON needs an editor command. Use an environment variable or promptString input instead.')
        if name.startswith('input:'):
            key = name[6:]
            item = inputs.get(key, {})
            if name in values:
                return values[name]
            if item.get('type', 'promptString') == 'pickString':
                options = item.get('options', [])
                options = [(str(i), option.get('label', option.get('value', '')) if isinstance(option, dict) else str(option), '')
                           for i, option in enumerate(options)]
                chosen = await ask_choice(item.get('description', key), options)
                if chosen is None:
                    raise ImportCancelled()
                selected = item['options'][int(chosen)]
                values[name] = selected.get('value', selected.get('label')) if isinstance(selected, dict) else selected
                return values[name]
            if item.get('type', 'promptString') != 'promptString':
                raise ValueError('supported input types: promptString and pickString')
            return await prompt(name, item.get('description', key), secret=item.get('password', True), default=item.get('default'))
        env_name = name[4:] if name.startswith('env:') else name
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', env_name):
            raise ValueError('unsupported MCP variable expression')
        if env_name in raw_env and env_name not in busy:
            busy.add(env_name)
            try:
                value = await walk(str(raw_env[env_name]))
            finally:
                busy.remove(env_name)
        elif os.environ.get(env_name) is not None:
            value = os.environ[env_name]
        elif env_name in busy and raw_env[env_name] not in (f'${{{env_name}}}', f'${{env:{env_name}}}'):
            raise ValueError('MCP environment variables contain a circular reference')
        elif fallback:
            value = fallback
        else:
            value = await prompt('env:' + env_name, env_name + ' (required by MCP JSON)')
        inherited[env_name] = value
        return value

    async def replace_matches(text, pattern, resolver):
        parts, start = [], 0
        for match in pattern.finditer(text):
            parts.extend((text[start:match.start()], str(await resolver(match))))
            start = match.end()
        return ''.join(parts) + text[start:]

    async def walk(value):
        if isinstance(value, dict):
            return {key: await walk(item) for key, item in value.items() if key != '_inputs'}
        if isinstance(value, list):
            return [await walk(item) for item in value]
        if not isinstance(value, str):
            return value
        value = await replace_matches(value, VARIABLE, lambda match: variable(match[1]))
        value = await replace_matches(value, PLACEHOLDER,
            lambda match: prompt('placeholder:' + match[0], 'Value for ' + match[0]))
        if re.fullmatch(r'your[-_][\w-]+', value, flags=re.I):
            value = await prompt('placeholder:' + value, 'Value for ' + value)
        return value

    resolved = unwrap_bridge(await walk(definition))
    if inherited and not (resolved.get('url') or resolved.get('serverUrl')):
        resolved['env'] = {**inherited, **resolved.get('env', {})}
    if resolved.get('url') or resolved.get('serverUrl'):
        # HTTP credentials have already been resolved into headers/OAuth.
        # Don't duplicate their source environment in config.json.
        resolved.pop('env', None)
    return normalize(resolved)


def unwrap_bridge(definition):
    """Use native transports for simple published mcp-remote launcher examples."""
    command = definition.get('command', [])
    command = [command] if isinstance(command, str) else command
    argv = [*command, *definition.get('args', [])]
    package = next((i for i, part in enumerate(argv) if part.split('@')[0] == 'mcp-remote'), None)
    if package is None or package + 1 >= len(argv) or not argv[package + 1].startswith(('https://', 'http://')):
        return definition
    rest = argv[package + 2:]
    headers = dict(definition.get('headers', {}))
    while rest:
        if len(rest) < 2 or rest[0] != '--header' or ':' not in rest[1]:
            return definition  # Preserve unfamiliar bridge flags, never silently discard them.
        key, value = rest[1].split(':', 1)
        headers[key.strip()] = value.strip()
        rest = rest[2:]
    result = {key: value for key, value in definition.items() if key not in ('command', 'args', 'type', 'transport')}
    url = argv[package + 1]
    result.update(type='sse' if url.rstrip('/').endswith('/sse') else 'http', url=url)
    if headers:
        result['headers'] = headers
    return result
