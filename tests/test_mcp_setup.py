"""Guided setup saves only reviewed connections and checks before enabling."""
from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from eirene.commands import dispatch
from eirene.commands import mcp_setup
from eirene.core.mcp_auth import MCPSecrets
from eirene.core.mcp_config import import_json, normalize


def wizard(config, workdir, choices, inputs=()):
    return SimpleNamespace(config=config, sandbox=SimpleNamespace(root=workdir),
        ask_choice=AsyncMock(side_effect=choices), ask_text=AsyncMock(side_effect=inputs),
        say=Mock(), _save_config=config.save,
        agent=SimpleNamespace(mcp=SimpleNamespace(close=AsyncMock()), provider=None))


async def test_json_connects_and_enables_without_provider_presets(config, workdir, monkeypatch):
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(mcp_setup, 'check_connection', check)
    app = wizard(config, workdir, ['connect'], ['{"mcpServers":{"example":{"url":"https://example.com/mcp"}}}'])
    await dispatch(app, '/mcp add')
    assert config.get('mcp_servers')['example'] == {
        'type': 'http', 'url': 'https://example.com/mcp', 'network': True, 'auth': 'auto'}
    assert config.get('mcp_enabled')['example'] is True
    assert app.ask_text.await_count == 1
    assert not app.ask_text.call_args.kwargs.get('secret', False)
    assert '(hidden)' not in app.ask_text.call_args.args[0]
    check.assert_awaited_once()


async def test_failed_connection_saved_disabled(config, workdir, monkeypatch):
    monkeypatch.setattr(mcp_setup, 'check_connection', AsyncMock(return_value=False))
    app = wizard(config, workdir, ['none', 'connect'])
    await dispatch(app, '/mcp add demo https://example.com/mcp')
    assert config.get('mcp_enabled')['demo'] is False
    assert config.get('mcp_servers')['demo']['url'] == 'https://example.com/mcp'


async def test_cancel_setup_does_not_save_or_connect(config, workdir, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr(mcp_setup, 'check_connection', check)
    app = wizard(config, workdir, ['token', None], ['private-token'])
    await dispatch(app, '/mcp add demo https://example.com/mcp')
    assert config.get('mcp_servers') == {}
    assert MCPSecrets('demo', 'https://example.com/mcp').read() == {}
    check.assert_not_awaited()


async def test_bearer_token_is_private_and_save_does_not_run_server(config, workdir, monkeypatch):
    check = AsyncMock()
    monkeypatch.setattr(mcp_setup, 'check_connection', check)
    app = wizard(config, workdir, ['token', 'save'], ['private-token'])
    await dispatch(app, '/mcp add demo https://example.com/mcp')
    assert 'private-token' not in json.dumps(config.get('mcp_servers'))
    assert MCPSecrets('demo', 'https://example.com/mcp').read()['headers'] == {'Authorization': 'Bearer private-token'}
    assert app.ask_text.call_args.kwargs['secret'] is True
    assert config.get('mcp_enabled')['demo'] is False
    check.assert_not_awaited()


async def test_json_import_supports_headers_and_multiple_transports(config, workdir):
    payload = json.dumps({'mcpServers': {
        'remote': {'type': 'http', 'url': 'https://example.com/mcp', 'headers': {'X-Key': 'secret'}},
        'local': {'command': sys.executable, 'args': ['-m', 'example']},
    }})
    app = wizard(config, workdir, ['save', 'save'], [payload])
    await dispatch(app, '/mcp import')
    assert set(config.get('mcp_servers')) == {'remote', 'local'}
    assert config.get('mcp_servers')['local']['command'][1:] == ['-m', 'example']
    assert 'secret' not in json.dumps(config.get('mcp_servers'))
    assert MCPSecrets('remote', 'https://example.com/mcp').read()['headers'] == {'X-Key': 'secret'}
    assert app.ask_choice.await_count == 1


async def test_json_file_import_and_missing_runtime_remain_manageable(config, workdir, monkeypatch):
    monkeypatch.setattr('eirene.core.mcp_config.shutil.which', lambda name: None)
    path = workdir / 'server config.jsonc'
    path.write_text('{/* config */"mcpServers":{"example":{"command":"missing-runtime","args":["server"]},},}')
    app = wizard(config, workdir, ['save'])
    await dispatch(app, '/mcp import ' + str(path))
    definition = config.get('mcp_servers')['example']
    assert definition['auto_setup'] is True
    assert definition['command'] == ['missing-runtime', 'server']
    assert config.get('mcp_enabled')['example'] is False
    app.ask_text.assert_not_awaited()


async def test_registered_oauth_credentials_are_saved_outside_config(config, workdir):
    payload = json.dumps({'servers': {'private': {'url': 'https://example.com/mcp', 'oauth': {
        'client_id': 'client', 'client_secret': '${input:secret}', 'redirect_uri': 'http://127.0.0.1:8765/callback'}}}})
    app = wizard(config, workdir, ['save'], [payload, 'private-client-secret'])
    await dispatch(app, '/mcp add')
    assert 'private-client-secret' not in json.dumps(config.get('mcp_servers'))
    assert MCPSecrets('private', 'https://example.com/mcp').read()['oauth']['client_secret'] == 'private-client-secret'


async def test_remote_environment_header_secrets_are_not_duplicated_in_config(config, workdir, monkeypatch):
    monkeypatch.setenv('HEADER_API_KEY', 'private-key-from-env')
    payload = '{"mcpServers":{"remote":{"url":"https://example.com/mcp","headers":{"Authorization":"Bearer ${HEADER_API_KEY}"}}}}'
    app = wizard(config, workdir, ['save'], [payload])
    await dispatch(app, '/mcp add')
    assert 'private-key-from-env' not in json.dumps(config.get('mcp_servers'))
    assert MCPSecrets('remote', 'https://example.com/mcp').read()['headers']['Authorization'] == 'Bearer private-key-from-env'


async def test_replacing_oauth_app_clears_previous_app_tokens(config, workdir):
    config.set('mcp_servers', {'remote': {'type': 'http', 'url': 'https://example.com/mcp', 'auth': 'oauth'}})
    store = MCPSecrets('remote', 'https://example.com/mcp')
    store.update(auth='oauth', oauth={'client_id': 'old-app'}, tokens={'access_token': 'old-account-token'})
    payload = '{"mcpServers":{"remote":{"url":"https://example.com/mcp","oauth":{"client_id":"new-app"}}}}'
    app = wizard(config, workdir, ['replace', 'save'], [payload])
    await dispatch(app, '/mcp import')
    assert store.read()['tokens'] is None
    assert store.read()['oauth']['client_id'] == 'new-app'


async def test_remove_connection_clears_activation_and_credentials(config, workdir):
    config.set('mcp_servers', {'demo': {'type': 'http', 'url': 'https://example.com/mcp'}})
    config.set('mcp_enabled', {'demo': True})
    MCPSecrets('demo', 'https://example.com/mcp').update(headers={'X-Key': 'secret'})
    app = wizard(config, workdir, ['remove'])
    await dispatch(app, '/mcp remove demo')
    assert config.get('mcp_servers') == {}
    assert config.get('mcp_enabled') == {}
    assert MCPSecrets('demo', 'https://example.com/mcp').read() == {}


async def test_local_json_collects_access_and_checks_before_enable(config, workdir, monkeypatch):
    monkeypatch.setattr(mcp_setup, 'check_connection', AsyncMock(return_value=True))
    payload = json.dumps({'mcpServers': {'local': {'command': sys.executable, 'args': ['-m', 'example'],
                                                'env': {'API_KEY': '${input:key}'}, 'read_paths': [str(workdir)]}}})
    app = wizard(config, workdir, ['connect'], [payload, 'secret'])
    await dispatch(app, '/mcp add')
    definition = config.get('mcp_servers')['local']
    assert definition['type'] == 'stdio'
    assert definition['env']['API_KEY'] == 'secret'
    assert definition['network'] is True
    assert str(workdir) in definition['read_paths']
    assert config.get('mcp_enabled')['local'] is True


async def test_plan_mode_test_does_not_connect(config, workdir, monkeypatch):
    from eirene.core.modes import Mode
    app = wizard(config, workdir, [])
    app.agent.mode = Mode.PLAN
    make = Mock()
    monkeypatch.setattr('eirene.core.mcp_remote.make_client', make)
    assert await mcp_setup.check_connection(app, 'remote', {'type': 'http', 'url': 'https://example.com/mcp'}) is False
    make.assert_not_called()


def test_package_launchers_get_persistent_caches_and_runtime_mounts(tmp_path, monkeypatch):
    from eirene.core.mcp_config import prepare_local
    launcher = tmp_path / 'node' / 'bin' / 'npx'
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    monkeypatch.setattr('eirene.core.mcp_config.shutil.which', lambda name: str(launcher))
    definition = prepare_local('example', {'command': ['npx', 'example-mcp']})
    assert definition['command'][1:] == ['-y', 'example-mcp']
    assert definition['env']['npm_config_cache'] in definition['write_paths']
    assert str(launcher.parent) in definition['read_paths']
    assert definition['startup_timeout'] == 120


async def test_add_flow_is_available_without_plugins_and_escape_returns_to_list(workdir):
    from eirene.app import Eirene
    from test_tui import content
    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app._start_command('/mcp')
        await pilot.pause()
        assert 'Add MCP server…' in content(app.picker)
        await pilot.press('enter')
        await pilot.pause()
        assert app._text_future is not None
        assert 'JSON' in app.prompt.placeholder
        await pilot.press('escape')
        await pilot.pause()
        assert app.picker.title == 'MCP servers — select to enable or disable'
        assert app.config.get('mcp_servers') == {}
        await pilot.press('escape')
        await app.command


async def test_ui_accepts_pasted_json_and_returns_to_server_list(workdir):
    from eirene.app import Eirene
    from test_tui import content
    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app._start_command('/mcp')
        await pilot.pause()
        await pilot.press('enter')
        await pilot.pause()
        app.prompt.value = '{"mcpServers":{"Example server":{"url":"https://example.com/mcp"}}}'
        await pilot.press('enter')
        await pilot.pause()
        assert app.picker.title == 'Example server — ready to connect'
        await pilot.press('down', 'enter')
        await pilot.pause()
        assert 'Example server (off)' in content(app.picker)
        assert app.config.get('mcp_servers')['Example server']['type'] == 'http'
        await pilot.press('escape')
        await app.command


@pytest.mark.parametrize('kind', ['http', 'streamable-http', 'sse'])
def test_normalize_remote_types(kind):
    definition = normalize({'type': kind, 'url': 'https://example.com/mcp'})
    assert definition['type'] == ('sse' if kind == 'sse' else 'http')
    assert definition['network'] is True


@pytest.mark.parametrize('url', ['ftp://example.com', 'https://user:secret@example.com/mcp',
                                 'file:///etc/passwd'])
def test_remote_url_validation(url):
    with pytest.raises(ValueError):
        normalize({'type': 'http', 'url': url})


def test_json_normalizes_common_configuration_shapes():
    assert normalize(import_json('{"mcp_servers":{"demo":{"serverUrl":"https://example.com/mcp"}}}')['demo'])['type'] == 'http'
    with pytest.raises(ValueError):
        import_json('{"mcpServers":{"demo":{"type":"websocket","url":"https://example.com"}}}')


def test_direct_http_declaration_defaults_to_network_access(config):
    from eirene.core.plugins import available_mcp_servers
    config.set('mcp_servers', {'demo': {'type': 'http', 'url': 'https://example.com/mcp'}})
    assert available_mcp_servers(config)['demo']['network'] is True
    config.set('mcp_servers', {'demo': {'type': 'http', 'url': 'https://example.com/mcp', 'network': False}})
    assert available_mcp_servers(config)['demo']['network'] is False
