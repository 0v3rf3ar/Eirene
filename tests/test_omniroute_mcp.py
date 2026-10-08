"""Optional management adapter installation, enablement, and connection bindings."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eirene.commands import dispatch
from eirene.core import paths, plugins
from eirene.core.config import Config
from eirene.core.omniroute_mcp import data_directory
from eirene.core.plugin_install import install
from eirene.providers.plugin_config import native_servers


@pytest.mark.parametrize('source',['omniroute','Omniroute','OmniRoute','OMNIROUTE'])
def test_optional_install_runs_no_external_installer_or_gateway(source,monkeypatch,tmp_path):
    def forbidden(*args,**kwargs):
        pytest.fail('adapter installation must not execute external commands')
    monkeypatch.setattr('eirene.core.plugin_install.subprocess.run',forbidden)
    monkeypatch.setattr('eirene.core.omniroute_mcp.shutil.which',lambda name: None)
    data=tmp_path/'external-gateway'
    data.mkdir()
    monkeypatch.setenv('EIRENE_OMNIROUTE_DATA_DIR',str(data))
    config=Config.load()
    assert plugins.merged_mcp_servers(config)=={}
    assert install(source)==('omniroute',0)
    assert config.provider is None
    assert not (paths.home()/'apps/omniroute').exists()
    assert plugins.merged_mcp_servers(config)=={}
    plugin=plugins.discover()[0]
    assert plugin.imported
    assert plugin.mcp_servers['gateway']['command']==['omniroute','--mcp']
    assert plugin.mcp_servers['gateway']['env']['DATA_DIR']==str(data)
    assert plugin.mcp_servers['gateway']['write_paths']==[str(data)]
    config.set('plugin_trust',{'omniroute':True})
    assert plugins.merged_mcp_servers(config)=={}
    config.set('mcp_enabled',{'omniroute__gateway':True})
    definition=plugins.merged_mcp_servers(config)['omniroute__gateway']
    assert definition['network'] is True
    assert definition['env']['OMNIROUTE_BASE_URL']=='http://localhost:20128'
    assert native_servers({'gateway':definition})['gateway']['args']==['--mcp']
    config.set_plugin('omniroute',False)
    assert plugins.merged_mcp_servers(config)=={}
    with pytest.raises(ValueError,match='already installed'):
        install(source)


async def test_slash_command_installs_optional_adapter(monkeypatch):
    config=Config.load()
    messages=[]
    app=SimpleNamespace(config=config,say=messages.append,
        agent=SimpleNamespace(reload_skills=lambda: None))
    monkeypatch.setattr('eirene.core.plugin_install.subprocess.run',
        lambda *args,**kwargs: pytest.fail('no Git clone needed'))
    await dispatch(app,'/plugins install Omniroute')
    assert plugins.discover()[0].name=='omniroute'
    assert '/mcp' in messages[-1]
    assert plugins.merged_mcp_servers(config)=={}


def test_saved_connection_updates_are_bound_only_after_manual_enable(monkeypatch):
    monkeypatch.setattr('eirene.core.omniroute_mcp.shutil.which',lambda name: None)
    install('omniroute')
    config=Config.load()
    config.set_provider('omniroute',api_key='first-secret',base_url='https://gateway.example/v1')
    assert plugins.merged_mcp_servers(config)=={}
    config.set('plugin_trust',{'omniroute':True})
    assert plugins.merged_mcp_servers(config)=={}
    config.set('mcp_enabled',{'omniroute__gateway':True})
    definition=plugins.merged_mcp_servers(config)['omniroute__gateway']
    assert definition['env']['OMNIROUTE_BASE_URL']=='https://gateway.example'
    assert definition['env']['OMNIROUTE_API_KEY']=='first-secret'
    config.set_provider('omniroute',api_key='second-secret',base_url='https://other.example/v1/')
    definition=plugins.merged_mcp_servers(config)['omniroute__gateway']
    assert definition['env']['OMNIROUTE_BASE_URL']=='https://other.example'
    assert definition['env']['OMNIROUTE_API_KEY']=='second-secret'
    assert 'first-secret' not in (paths.plugins_dir()/'omniroute/plugin.json').read_text()
    config.set('mcp_enabled',{})
    assert plugins.merged_mcp_servers(config)=={}


def test_explicit_env_overrides_preserve_separate_management_key(monkeypatch):
    monkeypatch.setattr('eirene.core.omniroute_mcp.shutil.which',lambda name: None)
    install('omniroute')
    index=paths.plugins_dir()/'omniroute/.eirene-plugin.json'
    body=json.loads(index.read_text())
    body['mcp_servers']['gateway']['env'].update(
        OMNIROUTE_BASE_URL='https://management.example',OMNIROUTE_API_KEY='management-key')
    index.write_text(json.dumps(body))
    config=Config.load()
    config.set_provider('omniroute',api_key='chat-only-key',base_url='https://chat.example/v1')
    config.set('plugin_trust',{'omniroute':True})
    assert plugins.merged_mcp_servers(config)=={}
    config.set('mcp_enabled',{'omniroute__gateway':True})
    definition=plugins.merged_mcp_servers(config)['omniroute__gateway']
    assert definition['env']['OMNIROUTE_API_KEY']=='management-key'
    assert definition['env']['OMNIROUTE_BASE_URL']=='https://management.example'


def test_resolves_node_and_external_npm_dependencies_for_isolation(tmp_path,monkeypatch):
    dependencies=tmp_path/'npm/node_modules'
    package=dependencies/'omniroute'
    cli=package/'bin/omniroute.mjs'
    cli.parent.mkdir(parents=True)
    cli.write_text('// external CLI')
    (package/'package.json').write_text('{"name":"omniroute"}')
    node=tmp_path/'node/bin/node'
    node.parent.mkdir(parents=True)
    node.write_text('node')
    monkeypatch.setattr('eirene.core.omniroute_mcp.shutil.which',
        lambda name: str(cli if name=='omniroute' else node))
    install('omniroute')
    config=Config.load()
    config.set('plugin_trust',{'omniroute':True})
    assert plugins.merged_mcp_servers(config)=={}
    config.set('mcp_enabled',{'omniroute__gateway':True})
    definition=plugins.merged_mcp_servers(config)['omniroute__gateway']
    assert definition['command']==[str(node),str(cli),'--mcp']
    assert str(dependencies) in definition['read_paths']
    assert str(node.parent) in definition['read_paths']
    assert str(paths.plugins_dir()/'omniroute') in definition['read_paths']


@pytest.mark.parametrize('legacy',[True,False])
def test_default_data_directory_matches_upstream(monkeypatch,tmp_path,legacy):
    monkeypatch.delenv('EIRENE_OMNIROUTE_DATA_DIR',raising=False)
    monkeypatch.setattr(Path,'home',lambda: tmp_path)
    monkeypatch.setenv('XDG_CONFIG_HOME',str(tmp_path/'config'))
    if legacy:
        (tmp_path/'.omniroute').mkdir()
    from eirene.core import omniroute_mcp
    monkeypatch.setattr(omniroute_mcp.os,'name','posix')
    assert data_directory()==tmp_path/('.omniroute' if legacy else 'config/omniroute')


async def test_network_access_applies_only_to_manually_enabled_mcp(workdir):
    from eirene.core.agent import Agent
    from eirene.core.session import Session
    from eirene.tools.sandbox import Sandbox
    config=Config.load()
    install('omniroute')
    session=Session.create(workdir)
    runner=Agent(session,config,Sandbox(workdir))
    assert runner.mcp.definitions=={}
    config.set('plugin_trust',{'omniroute':True})
    assert plugins.merged_mcp_servers(config)=={}
    config.set('mcp_enabled',{'omniroute__gateway':True})
    config.set('mcp_enabled',{'omniroute__gateway':True,'other':True})
    config.set('mcp_servers',{'other':{'command':['other-tool'],'network':'true'}})
    runner=Agent(session,config,Sandbox(workdir))
    assert runner.mcp.definitions['omniroute__gateway']['_isolate_network'] is False
    assert runner.mcp.definitions['other']['_isolate_network'] is True
    assert config.get('isolate_network') is True
    await runner.close()
    session.close()
