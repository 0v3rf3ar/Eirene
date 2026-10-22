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
