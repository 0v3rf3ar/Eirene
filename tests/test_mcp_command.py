"""Manual MCP grants and provider availability follow explicit installation."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eirene.commands import dispatch
from eirene.commands.connect import _pick
from eirene.core import plugins, skills
from eirene.core.config import Config
from eirene.core.errors import CommandError
from eirene.core.plugin_install import install
from eirene.providers import registry


def app_for(config, choices):
    return SimpleNamespace(config=config, say=lambda *args: None,
        ask_choice=AsyncMock(side_effect=choices), _save_config=config.save,
        agent=SimpleNamespace(mcp=SimpleNamespace(close=AsyncMock()), reload_skills=lambda: None))


async def test_connect_omniroute_requires_plugin_and_does_not_enable_mcp(config):
    app = app_for(config, ['', ''])
    assert not registry.available('omniroute')
    with pytest.raises(CommandError, match='/plugins install omniroute'):
        await _pick(app, 'omniroute')
    await _pick(app, '')
    assert 'omniroute' not in [row[0] for row in app.ask_choice.call_args.args[1]]
    install('omniroute')
    assert registry.available('omniroute')
    assert await _pick(app, 'omniroute') == 'omniroute'
    await _pick(app, '')
    assert 'omniroute' in [row[0] for row in app.ask_choice.call_args.args[1]]
    assert plugins.merged_mcp_servers(config) == {}
    assert not skills.discover()


async def test_mcp_picker_enables_persists_and_disables_without_hook_trust(config):
    install('omniroute')
    config.set('mcp_servers', {'docs': {'command': ['docs-mcp']}})
    assert plugins.merged_mcp_servers(config) == {}
    app = app_for(config, ['omniroute__gateway', ''])
    await dispatch(app, '/mcp')
    first = app.ask_choice.call_args_list[0].args[1]
    assert {row[1] for row in first} == {'off  docs', 'off  omniroute / gateway', 'done'}
    assert set(plugins.merged_mcp_servers(Config.load())) == {'omniroute__gateway'}
    assert config.get('plugin_trust', {}) == {}
    assert app.ask_choice.call_args.args[1][1][1] == 'on  omniroute / gateway'
    app.agent.mcp.close.assert_awaited_once()
    app.ask_choice = AsyncMock(side_effect=['omniroute__gateway', ''])
    await dispatch(app, '/mcp')
    assert plugins.merged_mcp_servers(Config.load()) == {}
    assert app.agent.mcp.close.await_count == 2


async def test_disabled_plugin_mcp_cannot_be_enabled(config):
    install('omniroute')
    config.set_plugin('omniroute', False)
    app = app_for(config, ['omniroute__gateway', ''])
    await dispatch(app, '/mcp')
    assert config.get('mcp_enabled') == {}
    assert 'plugin disabled' in app.ask_choice.call_args.args[1][0][2]
    app.agent.mcp.close.assert_not_awaited()


@pytest.mark.parametrize('action', ['untrust', 'refresh'])
async def test_plugin_revocation_clears_mcp_grant(config, action):
    install('omniroute')
    config.set('mcp_enabled', {'omniroute__gateway': True})
    app = app_for(config, [])
    await dispatch(app, '/plugins ' + action + ' omniroute')
    assert plugins.merged_mcp_servers(Config.load()) == {}


async def test_empty_mcp_list_and_active_turn_do_not_prompt(config):
    app = app_for(config, [])
    await dispatch(app, '/mcp')
    install('omniroute')
    app.turn = SimpleNamespace(done=lambda: False)
    await dispatch(app, '/mcp')
    app.ask_choice.assert_not_awaited()
    assert plugins.merged_mcp_servers(config) == {}


async def test_first_launch_does_not_install_default_skills(workdir):
    from eirene.app import Eirene
    app = Eirene(workdir)
    async with app.run_test():
        assert skills.discover() == []
        assert app.agent.skills == []
