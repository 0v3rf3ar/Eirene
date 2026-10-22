"""Documented vendor configurations exercise the same generic import path."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from eirene.core.mcp_config import import_json, normalize, prepare_local, transport
from eirene.core.mcp_import import ImportCancelled, resolve_definition, unwrap_bridge

EXAMPLES = Path(__file__).parents[1] / 'docs' / 'mcp-examples'
CASES = json.loads((EXAMPLES / 'index.json').read_text())


def answer(description, **kwargs):
    name = description.lower()
    if 'redis_url' in name:
        return 'redis://127.0.0.1:6379/0'
    if 'mongodb_url' in name:
        return 'mongodb://127.0.0.1:27017/example'
    if 'database_uri' in name:
        return 'postgresql://127.0.0.1:5432/example'
    if 'es_url' in name or 'address' in name:
        return 'https://example.com'
    return 'test-value'


@pytest.mark.parametrize('case', CASES, ids=lambda case: case['id'])
async def test_documented_configuration_import_and_runtime(case, workdir, monkeypatch):
    monkeypatch.setattr('eirene.core.mcp_config.shutil.which', lambda executable: '/usr/bin/' + Path(executable).name)
    servers = import_json((EXAMPLES / case['file']).read_text())
    assert len(servers) == 1
    name, raw = next(iter(servers.items()))
    definition = await resolve_definition(raw, workdir, AsyncMock(side_effect=answer), AsyncMock())
    assert definition['type'] in ('stdio', 'http', 'sse')
    assert '_inputs' not in definition
    assert '${' not in json.dumps(definition)
    if transport(definition) == 'stdio':
        definition = prepare_local(name, definition)
        assert definition['network'] is True
        assert Path(definition['_runtime_home']).is_dir()
        assert definition['env']['HOME'] == definition['_runtime_home']
        assert definition['startup_timeout'] >= 120
    else:
        assert definition['url'].startswith(('https://', 'http://127.0.0.1'))
        assert definition['auth'] in ('auto', 'oauth', 'none')


@pytest.mark.parametrize('wrapper', ['mcpServers', 'mcp_servers', 'servers', 'mcp.servers', 'mcp', 'bare'])
def test_common_client_wrappers_and_human_readable_names(wrapper):
    servers = {'Redis MCP Server': {'command': 'uvx', 'args': ['redis-mcp-server']}}
    body = servers if wrapper == 'bare' else {'mcp': {'servers': servers}} if wrapper == 'mcp.servers' else {wrapper: servers}
    assert set(import_json(json.dumps(body))) == {'Redis MCP Server'}


def test_jsonc_fences_bom_and_trailing_commas_preserve_string_contents():
    value = '\ufeff```jsonc\n{ // comment\n "servers": {"demo": {"url": "https://example.com/a//b?value=,}", /* comment */},},}\n```'
    definition = import_json(value)['demo']
    assert definition['url'] == 'https://example.com/a//b?value=,}'


async def test_vscode_inputs_environment_and_workspace_variables(workdir, monkeypatch):
    monkeypatch.setenv('EXISTING_TOKEN', 'from-shell')
    raw = import_json(json.dumps({'inputs': [{'id': 'token', 'type': 'promptString', 'description': 'PAT', 'password': True}],
        'servers': {'demo': {'command': 'server', 'args': ['${workspaceFolder}', '${userHome}'],
        'env': {'API_KEY': '${input:token}', 'CHAINED': '${API_KEY}'},
        'headers': {'X-Existing': '${env:EXISTING_TOKEN}', 'X-Default': '${ABSENT_MCP_TEST_VAR:-fallback}'}}}}))['demo']
    ask = AsyncMock(return_value='private-value')
    definition = await resolve_definition(raw, workdir, ask, AsyncMock())
    assert definition['command'][1:] == [str(workdir), str(Path.home())]
    assert definition['env']['API_KEY'] == definition['env']['CHAINED'] == 'private-value'
    assert definition['env']['EXISTING_TOKEN'] == 'from-shell'
    assert definition['headers']['X-Default'] == 'fallback'
    ask.assert_awaited_once_with('PAT', secret=True)


async def test_pick_string_input_and_cancel(workdir):
    definition = {'command': 'server', 'args': ['${input:region}'], '_inputs': [
        {'id': 'region', 'type': 'pickString', 'options': [{'label': 'Europe', 'value': 'eu'}, 'us']} ]}
    resolved = await resolve_definition(definition, workdir, AsyncMock(), AsyncMock(return_value='0'))
    assert resolved['command'] == ['server', 'eu']
    with pytest.raises(ImportCancelled):
        await resolve_definition(definition, workdir, AsyncMock(), AsyncMock(return_value=None))


async def test_missing_variable_is_prompted_once_and_cancellation_stops_import(workdir, monkeypatch):
    monkeypatch.delenv('MCP_TEST_SECRET', raising=False)
    raw = {'url': 'https://example.com/mcp', 'headers': {'Authorization': 'Bearer ${MCP_TEST_SECRET}', 'X-Again': '${MCP_TEST_SECRET}'}}
    ask = AsyncMock(return_value='token')
    resolved = await resolve_definition(raw, workdir, ask, AsyncMock())
    assert resolved['headers']['Authorization'] == 'Bearer token'
    assert ask.await_count == 1
    with pytest.raises(ImportCancelled):
        await resolve_definition(raw, workdir, AsyncMock(return_value=None), AsyncMock())


async def test_circular_environment_and_editor_commands_fail_without_execution(workdir):
    for raw in [{'command': 'server', 'env': {'A': '${B}', 'B': '${A}'}},
                {'url': 'https://example.com/mcp', 'headers': {'Token': '${command:runAnything}'}}]:
        with pytest.raises(ValueError):
            await resolve_definition(raw, workdir, AsyncMock(), AsyncMock())


@pytest.mark.parametrize('package', ['mcp-remote', 'mcp-remote@latest'])
def test_simple_stdio_bridges_use_native_transport(package):
    definition = unwrap_bridge({'command': 'npx', 'args': ['-y', package, 'https://example.com/sse', '--header', 'Authorization: Bearer key']})
    assert definition == {'type': 'sse', 'url': 'https://example.com/sse', 'headers': {'Authorization': 'Bearer key'}}
    original = {'command': 'npx', 'args': ['mcp-remote', 'https://example.com/mcp', '--unknown', 'option']}
    assert unwrap_bridge(original) == original


def test_single_definition_and_path_traversal_names():
    assert set(import_json('{"command":"server"}', name='My server')) == {'My server'}
    for name in ('../escape', '/absolute', '..', ':add', 'bad\nname'):
        with pytest.raises(ValueError):
            import_json(json.dumps({'mcpServers': {name: {'command': 'server'}}}))


def test_oauth_aliases_and_non_dcr_client_settings():
    definition = normalize({'url': 'https://example.com/mcp',
        'oauth': {'clientId': 'id', 'clientSecret': 'secret', 'redirectUri': 'http://127.0.0.1:8765/callback',
                  'authorizationParams': {'access_type': 'offline'}}})
    assert definition['auth'] == 'oauth'
    assert definition['oauth']['client_id'] == 'id'
    assert definition['oauth']['authorization_params']['access_type'] == 'offline'


def test_manifest_covers_every_requested_integration_once():
    assert {case['id'] for case in CASES} == {
        'cloudflare', 'burpsuite', 'google-workspace', 'ahrefs', 'redis', 'mongodb', 'elasticsearch',
        'puppeteer', 'webflow', 'microsoft365', 'x-twitter', 'github', 'docker', 'google-drive',
        'terraform', 'kubernetes', 'sentry', 'chrome-devtools', 'context7', 'figma', 'notion',
        'slack', 'postgresql', 'playwright'}
    assert len(CASES) == 24
