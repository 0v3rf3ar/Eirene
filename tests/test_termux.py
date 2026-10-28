"""Termux shell discovery and explicit execution permissions."""
import shutil

import pytest

from eirene.core import platforms
from eirene.core.agent import ToolFinished
from eirene.core.modes import Mode
from eirene.providers.base import Done, TextDelta, ToolCall
from eirene.tools import shell
from test_agent import Script, build, drive


@pytest.fixture
def termux(monkeypatch):
    monkeypatch.setenv('PREFIX', '/data/data/com.termux/files/usr')


def test_termux_host_and_shell_paths(termux, monkeypatch):
    prefix = '/data/data/com.termux/files/usr/bin/'
    monkeypatch.setattr(shutil, 'which', lambda name: prefix + name if name in ('bash', 'sh', 'pkg') else None)
    host = platforms.Host.detect()
    assert platforms.is_termux()
    assert host.system == 'Android' and host.distribution == 'Termux'
    assert host.package_manager == 'pkg' and host.shell == 'bash'
    assert shell.posix_argv('echo ok')[0] == prefix + 'bash'
    assert shell.posix_argv('echo ok', 'sh')[0] == prefix + 'sh'
    assert 'explicit approval' in platforms.guidance()


@pytest.mark.parametrize('mode', [Mode.AUTO, Mode.MANUAL, Mode.PLAN])
async def test_termux_commands_cannot_bypass_approval(termux, workdir, mode):
    runner = build(workdir, Script(
        [ToolCall('cmd', 'run_command', {'command': 'echo hello'}), Done()],
        [TextDelta('done'), Done()]), mode=mode)
    runner.approve = None
    events = await drive(runner)
    result = next(e for e in events if isinstance(e, ToolFinished))
    assert result.is_error
    assert ('plan mode' if mode is Mode.PLAN else 'no one') in result.result


async def test_termux_approved_command_runs(termux, workdir):
    runner = build(workdir, Script(
        [ToolCall('cmd', 'run_command', {'command': 'echo termux-approved'}), Done()],
        [TextDelta('done'), Done()]))
    approvals = []
    async def approve(*args):
        approvals.append(args)
        return 'yes'
    runner.approve = approve
    events = await drive(runner)
    results = [e for e in events if isinstance(e, ToolFinished)]
    assert approvals and 'Termux' in approvals[0][-1]
    assert not results[-1].is_error and 'termux-approved' in results[-1].result


async def test_termux_plan_can_read_workspace_files(termux, workdir):
    (workdir / 'example.txt').write_text('hello Termux')
    runner = build(workdir, Script(
        [ToolCall('read', 'read_file', {'path': 'example.txt'}), Done()],
        [TextDelta('done'), Done()]), mode=Mode.PLAN)
    results = [e for e in await drive(runner) if isinstance(e, ToolFinished)]
    assert not results[-1].is_error and 'hello Termux' in results[-1].result


def test_termux_hooks_and_mcp_need_consent_not_a_sandbox(termux, config):
    from eirene.core.permissions import isolation
    assert isolation(config) == 'none'
    config.set('execution_isolation', 'bubblewrap')  # An explicit backend still fails closed.
    assert isolation(config) == 'bubblewrap'


def test_isolation_is_unchanged_off_termux(monkeypatch, config):
    monkeypatch.delenv('PREFIX', raising=False)
    monkeypatch.delenv('TERMUX_VERSION', raising=False)
    monkeypatch.setattr(platforms.sys, 'platform', 'linux')
    from eirene.core.permissions import isolation
    assert isolation(config) == 'auto'


async def test_termux_trusted_plugin_hook_runs_without_bubblewrap(termux, tmp_path, config, box, monkeypatch):
    import json
    from eirene.core import plugins
    from eirene.core.plugin_install import install
    from eirene.core.plugin_runtime import PluginRuntime
    from eirene.core.plugin_health import report
    from eirene.tools import isolation as isolation_backends
    real_which = shutil.which
    monkeypatch.setattr(isolation_backends.shutil, 'which',
                        lambda name: None if name == 'bwrap' else real_which(name))
    root = tmp_path / 'starter'
    (root / 'hooks').mkdir(parents=True)
    (root / 'plugin.json').write_text(json.dumps({'name': 'starter'}))
    (root / 'hooks/hooks.json').write_text(json.dumps({'hooks': {'SessionStart': [
        {'matcher': 'startup', 'hooks': [{'type': 'command', 'command': 'echo ready from android'}]}]}}))
    (root / '.mcp.json').write_text(json.dumps({'mcpServers': {'docs': {'command': 'node', 'args': ['s.js']}}}))
    install(str(root))
    config.set('plugin_trust', {'starter': True})
    runtime = PluginRuntime('termux-session')
    await runtime.submit('hello', box, config)
    assert 'ready from android' in runtime.block(config)
    config.set('mcp_enabled', {'starter__docs': True})
    from eirene.core.agent import Agent
    from eirene.core.session import Session
    runner = Agent(Session.create(box.root), config, box)
    assert {d['_isolation'] for d in runner.mcp.definitions.values()} == {'none'}
    await runner.close()
    shown = report(plugins.discover()[0], config)
    assert "Android has no Eirene sandbox" in shown
