"""Portable command and lifecycle behavior, independent of the selected model."""
import json
from types import SimpleNamespace
from pathlib import Path

import pytest

from eirene.commands import commands, dispatch, lookup
from eirene.commands.plugin_commands import expand
from eirene.core import paths, plugins
from eirene.core.agent import Agent, Answer
from eirene.core.config import Config
from eirene.core.plugin_install import install
from eirene.core.plugin_runtime import PluginRuntime, parse_output
from eirene.core.session import Session
from eirene.core.errors import ToolError
from eirene.core.modes import Mode
from eirene.providers.base import Done, TextDelta


def bundle(tmp_path, name="demo"):
    root = tmp_path / name
    (root / '.claude-plugin').mkdir(parents=True)
    (root / '.claude-plugin/plugin.json').write_text(json.dumps({"name": name, "version": "4.0.0"}))
    (root / 'commands').mkdir()
    (root / 'commands/review.md').write_text('---\ndescription: Review carefully\n---\nInspect $ARGUMENTS; first $0.')
    (root / 'hooks').mkdir()
    (root / 'hooks/hooks.json').write_text(json.dumps({"hooks": {
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": 'echo start'}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": 'echo prompt'}]}],
        "SubagentStart": [{"hooks": [{"type": "command", "command": 'echo agent'}]}],
    }}))
    (root / '.mcp.json').write_text(json.dumps({"mcpServers": {"docs": {
        "command": "node", "args": ["${CLAUDE_PLUGIN_ROOT}/server.js"]}}}))
    return root


def test_import_commands_hooks_mcp_and_report_limits(tmp_path, config):
    assert install(str(bundle(tmp_path))) == ("demo", 0)
    plugin = plugins.discover()[0]
    assert len(plugin.commands) == 1
    assert set(plugin.lifecycle) == {"SessionStart", "UserPromptSubmit"}
    assert any('SubagentStart' in w for w in plugin.warnings)
    assert plugins.merged_mcp_servers(config) == {}
    config.set('plugin_trust', {'demo': True})
    assert plugins.merged_mcp_servers(config) == {}
    config.set('mcp_enabled', {'demo__docs': True})
    server = plugins.merged_mcp_servers(config)['demo__docs']
    assert server['command'] == ['node', str(plugin.path / 'server.js')]
    assert server['read_paths'] == [str(plugin.path)]


def test_alias_collisions_and_disabled_plugins(tmp_path, config):
    install(str(bundle(tmp_path)))
    assert lookup('review').name == 'review'  # built-in wins
    assert lookup('demo:review').summary == 'Review carefully'
    app = SimpleNamespace(config=config)
    config.set_plugin('demo', False)
    assert lookup('demo:review', app) is None
    assert not any(c.name.startswith('demo:') for c in commands(app))


def test_expansion_is_literal_and_supports_positional_arguments():
    assert expand('$0 $ARGUMENTS[1] $ARGUMENTS', '"one two" three') == 'one two three "one two" three'
    assert expand('Review this', 'file.py') == 'Review this\n\nUser arguments: file.py'
    assert expand('$ARGUMENTS', '$0 $(touch nope)') == '$0 $(touch nope)'


async def test_dispatch_sends_expanded_command_through_normal_turn(tmp_path, config):
    install(str(bundle(tmp_path)))
    received = []
    async def push(block):
        pass
    async def run_turn(text, **kwargs):
        received.append((text, kwargs))
    app = SimpleNamespace(config=config, turn=None, push=push, _run_turn=run_turn, say=lambda *a: None)
    await dispatch(app, '/demo:review src/main.py')
    await app.turn
    assert 'Inspect src/main.py; first src/main.py.' in received[0][0]
    assert received[0][1]['record_text'] == '/demo:review src/main.py'


async def test_lifecycle_trust_plan_start_once_stdin_and_disable(tmp_path, config, box, monkeypatch):
    install(str(bundle(tmp_path)))
    calls = []
    async def run(command, cwd, **kwargs):
        calls.append((command, kwargs))
        payload = json.loads(kwargs['input_text'])
        return SimpleNamespace(ok=True, output=json.dumps({'hookSpecificOutput': {
            'additionalContext': payload['hook_event_name'] + ':' + payload['prompt']}}))
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', run)
    runtime = PluginRuntime('session-1')
    await runtime.submit('one', box, config)
    assert not calls
    config.set('plugin_trust', {'demo': True})
    await runtime.submit('plan', box, config, plan=True)
    assert not calls
    await runtime.submit('one', box, config)
    await runtime.submit('two', box, config)
    assert [c[0] for c in calls] == ['echo start', 'echo prompt', 'echo prompt']
    assert calls[0][1]['env']['PLUGIN_DATA'].endswith('demo/session-1')
    assert 'UserPromptSubmit:two' in runtime.block(config)
    config.set_plugin('demo', False)
    assert runtime.block(config) == ''
    await runtime.submit('three', box, config)
    assert len(calls) == 3


@pytest.mark.parametrize('native', [False, True])
async def test_command_body_and_hook_context_reach_provider(tmp_path, config, box, monkeypatch, native):
    root = bundle(tmp_path)
    (root / '.mcp.json').unlink()
    install(str(root))
    config.set('plugin_trust', {'demo': True})
    async def run(*args, **kwargs):
        return SimpleNamespace(ok=True, output='Keep changes minimal.')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', run)
    class Provider:
        supports_tools = not native
        owns_context = native
        async def stream(self, messages, model, **kwargs):
            assert 'Keep changes minimal.' in kwargs['system']
            assert 'Expanded instruction to inspect the diff.' in kwargs['system']
            assert messages[-1]['content'] == '/demo:review'
            yield TextDelta('done')
            yield Done('stop')
    agent = Agent(Session.create(box.root), config, box)
    agent.use(Provider(), 'fake', 'model')
    events = [e async for e in agent.run('Expanded instruction to inspect the diff.', record_text='/demo:review')]
    assert any(isinstance(e, Answer) for e in events)
    await agent.close()


def test_hook_block_and_output_contract():
    assert parse_output('{"hookSpecificOutput":{"additionalContext":"rules"},"systemMessage":"active"}') == ('rules', 'active')
    with pytest.raises(ToolError, match='stop here'):
        parse_output('{"decision":"block","reason":"stop here"}')


@pytest.mark.parametrize('field', ['skills', 'commands', 'hooks', 'mcpServers'])
def test_declared_paths_cannot_escape(tmp_path, field):
    root = bundle(tmp_path)
    (root / '.claude-plugin/plugin.json').write_text(json.dumps({'name': 'demo', field: '../outside'}))
    with pytest.raises(ValueError, match='leaves its directory'):
        install(str(root))
    assert not (paths.plugins_dir() / 'demo').exists()


def test_native_mcp_configuration_and_changes_reset_threads():
    from eirene.providers.codex_subscription import CodexSubscription
    from eirene.providers.claude_code import ClaudeCode
    servers = {'demo__docs': {'command': ['node', '/tmp/server.js'], 'env': {'MODE': 'test'}}}
    codex, claude = CodexSubscription(), ClaudeCode()
    codex._thread_id = 'old'
    claude._session_id = 'old'
    for provider in (codex, claude):
        provider.set_plugins(servers)
        assert provider._plugin_servers['demo__docs']['args'] == ['/tmp/server.js']
    assert not codex._thread_id and not claude._session_id
    assert codex._thread_options('model')['config']['mcp_servers']['demo__docs']['command'] == 'node'
    for provider in (codex, claude):
        provider.set_plugins({})
        assert provider._plugin_servers == {}


async def test_ponytail_replaces_startup_rules_on_mode_change(tmp_path, config, box, monkeypatch):
    root = bundle(tmp_path, 'ponytail')
    (root / 'hooks/ponytail-instructions.js').write_text('// fixture: rule generator')
    install(str(root))
    config.set('plugin_trust', {'ponytail': True})
    async def run(command, cwd, **kwargs):
        env = kwargs['env']
        if 'EIRENE_PONYTAIL_MODE' in env:
            return SimpleNamespace(ok=True, output='Rules for ' + env['EIRENE_PONYTAIL_MODE'])
        state = Path(env['PLUGIN_DATA']) / '.ponytail-active'
        payload = json.loads(kwargs['input_text'])
        if payload['hook_event_name'] == 'SessionStart':
            state.write_text('full')
        if payload['prompt'] == '/ponytail ultra':
            state.write_text('ultra')
        elif payload['prompt'] == '/ponytail off':
            state.unlink(missing_ok=True)
        return SimpleNamespace(ok=True, output='startup full rules')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', run)
    runtime = PluginRuntime('mode-test')
    await runtime.submit('build', box, config)
    assert runtime.ponytail_mode == 'full'
    await runtime.submit('/ponytail ultra', box, config)
    assert runtime.context['ponytail', 'SessionStart'] == 'Rules for ultra'
    await runtime.submit('/ponytail off', box, config)
    assert 'Rules for' not in runtime.context['ponytail', 'SessionStart']
    assert runtime.ponytail_mode == 'off'


def ponytail_app(tmp_path, config, box):
    root = bundle(tmp_path, 'ponytail')
    for slug in ('ponytail', 'ponytail-help'):
        directory = root / 'skills' / slug
        directory.mkdir(parents=True)
        (directory / 'SKILL.md').write_text('---\ndescription: Ponytail control\n---\nInstructions')
    (root / 'hooks/ponytail-instructions.js').write_text('// fixture')
    install(str(root))
    messages = []
    async def forbidden(*args, **kwargs):
        pytest.fail('local plugin controls must not start an AI turn')
    return SimpleNamespace(config=config, sandbox=box, turn=None,
        agent=SimpleNamespace(mode=Mode.AUTO, plugin_runtime=PluginRuntime('controls')),
        push=forbidden, _run_turn=forbidden, say=lambda *args: messages.append(args)), messages


@pytest.mark.parametrize('command', ['ponytail', 'ponytail:ponytail'])
async def test_ponytail_controls_are_local_and_persist_rules(tmp_path, config, box, monkeypatch, command):
    app, messages = ponytail_app(tmp_path, config, box)
    config.set('plugin_trust', {'ponytail': True})
    calls = []
    async def run(command, cwd, **kwargs):
        env = kwargs['env']
        if 'EIRENE_PONYTAIL_MODE' in env:
            return SimpleNamespace(ok=True, output='Rules for ' + env['EIRENE_PONYTAIL_MODE'])
        payload = json.loads(kwargs['input_text'])
        calls.append(payload)
        state = Path(env['PLUGIN_DATA']) / '.ponytail-active'
        if payload['hook_event_name'] == 'SessionStart':
            state.write_text('full')
        parts = payload['prompt'].split()
        if len(parts) == 3 and parts[1] == 'default':
            settings = Path(env['XDG_CONFIG_HOME']) / 'ponytail/config.json'
            settings.parent.mkdir(exist_ok=True)
            settings.write_text(json.dumps({'defaultMode': parts[2]}))
        elif len(parts) == 2:
            if parts[1] == 'off':
                state.unlink(missing_ok=True)
            else:
                state.write_text(parts[1])
        return SimpleNamespace(ok=True, output='mode confirmation')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', run)
    await dispatch(app, f'/{command}\tULTRA')
    assert app.turn is None
    assert app.agent.plugin_runtime.ponytail_mode == 'ultra'
    assert 'Rules for ultra' in app.agent.plugin_runtime.block(config)
    await dispatch(app, f'/{command} default lite')
    assert 'default set to lite' in messages[-1][0]
    assert app.agent.plugin_runtime.ponytail_mode == 'ultra'
    await dispatch(app, f'/{command} off')
    await dispatch(app, f'/{command}')
    assert 'Ponytail mode: off' in messages[-1][0]
    assert 'Rules for' not in app.agent.plugin_runtime.block(config)
    assert ('ponytail', 'UserPromptSubmit') not in app.agent.plugin_runtime.context
    assert sum(c['hook_event_name'] == 'SessionStart' for c in calls) == 1


@pytest.mark.parametrize('args', ['ultra', 'default lite', 'nonsense', 'default review', 'ultra extra'])
async def test_ponytail_control_errors_stay_local(tmp_path, config, box, monkeypatch, args):
    app, messages = ponytail_app(tmp_path, config, box)
    async def forbidden(*args, **kwargs):
        pytest.fail('invalid or untrusted controls must not execute hooks')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', forbidden)
    await dispatch(app, '/ponytail ' + args)
    assert messages[-1][1] == 'warn'
    assert app.turn is None


async def test_ponytail_help_and_plan_controls_do_not_call_provider(tmp_path, config, box, monkeypatch):
    app, messages = ponytail_app(tmp_path, config, box)
    async def forbidden(*args, **kwargs):
        pytest.fail('help and plan controls must not execute hooks')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', forbidden)
    await dispatch(app, '/ponytail-help')
    assert '/ponytail-review' in messages[-1][0]
    config.set('plugin_trust', {'ponytail': True})
    app.agent.mode = Mode.PLAN
    await dispatch(app, '/ponytail off')
    assert 'disabled in plan mode' in messages[-1][0]
    config.set_plugin('ponytail', False)
    await dispatch(app, '/ponytail ultra')
    assert 'unknown command' in messages[-1][0]


async def test_local_controls_run_only_the_selected_plugin_hooks(tmp_path, config, box, monkeypatch):
    install(str(bundle(tmp_path)))
    ponytail_app(tmp_path, config, box)
    config.set('plugin_trust', {'ponytail': True, 'demo': True})
    called = []
    async def run(command, cwd, **kwargs):
        called.append(kwargs['env']['PLUGIN_ROOT'])
        return SimpleNamespace(ok=True, output='')
    monkeypatch.setattr('eirene.core.plugin_runtime.shell.run', run)
    runtime = PluginRuntime('selected')
    runtime.context['demo', 'SessionStart'] = 'Existing demo rules'
    await runtime.submit('/ponytail off', box, config, only='ponytail')
    assert all(path.endswith('/ponytail') for path in called)
    assert runtime.context['demo', 'SessionStart'] == 'Existing demo rules'


async def test_composer_routes_ponytail_control_without_an_ai_turn(tmp_path, config, box, monkeypatch):
    from eirene.app import Eirene
    from eirene.ui.composer import Prompt

    ponytail_app(tmp_path, config, box)
    app = Eirene(box.root)
    app.config.set('plugin_trust', {'ponytail': True})
    async def forbidden(*args, **kwargs):
        pytest.fail('composer started an AI turn for a mode switch')
    async def submit(prompt, sandbox, config, **kwargs):
        assert prompt == '/ponytail ultra'
        assert kwargs == {'only': 'ponytail'}
        app.agent.plugin_runtime.ponytail_mode = 'ultra'
        return []
    monkeypatch.setattr(app, '_run_turn', forbidden)
    monkeypatch.setattr(app.agent.plugin_runtime, 'submit', submit)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        await app.on_prompt_sent(Prompt.Sent('/ponytail ultra'))
        await app.command
        assert app.turn is None
        assert app.agent.plugin_runtime.ponytail_mode == 'ultra'


def test_native_skill_budget_keeps_discoverable_paths(tmp_path):
    from eirene.core.skills import Skill, inline_block
    path = tmp_path / 'SKILL.md'
    path.write_text('Very long skill instructions')
    text = inline_block([Skill('demo:long', path, 'Long', 'Use for reviews', 100)], budget=1)
    assert str(path) in text
    assert 'Use for reviews' in text


async def test_refresh_migrates_legacy_import_without_overwriting_resources(tmp_path, config):
    from eirene.commands.plugins import run
    root = bundle(tmp_path)
    install(str(root))
    installed = paths.plugins_dir() / 'demo'
    (installed / '.eirene-plugin.json').unlink()
    (installed / 'plugin.json').write_text(json.dumps({'version': 1, 'name': 'demo', 'skills': []}))
    config.set('plugin_trust', {'demo': True})
    app = SimpleNamespace(config=config, turn=None, say=lambda *a: None,
                          _save_config=lambda: None,
                          agent=SimpleNamespace(reload_skills=lambda: None))
    await run(app, 'refresh demo')
    plugin = plugins.discover()[0]
    assert len(plugin.commands) == 1
    assert plugin.lifecycle['SessionStart']
    assert not plugins.executable_enabled(plugin, config)
    assert (installed / 'commands/review.md').read_text() == (root / 'commands/review.md').read_text()


def test_root_manifest_is_preserved_for_refresh(tmp_path, config):
    root = tmp_path / 'universal'
    root.mkdir()
    (root / 'custom-hooks.json').write_text(json.dumps({'hooks': {'SessionStart': [
        {'hooks': [{'type': 'command', 'command': 'echo hello'}]}]}}))
    original = json.dumps({'name': 'universal', 'version': '2.1.0', 'hooks': './custom-hooks.json'})
    (root / 'plugin.json').write_text(original)
    install(str(root))
    installed = paths.plugins_dir() / 'universal'
    assert (installed / 'plugin.json').read_text() == original
    from eirene.core.plugin_manifest import normalize
    assert normalize(installed, 'universal')['lifecycle']['SessionStart'][0]['command'] == 'echo hello'


@pytest.mark.parametrize('manifest', ['.agent-plugin/plugin.json', '.github/plugin/plugin.json', 'plugin.json'])
def test_portable_manifest_and_root_mcp_file(tmp_path, config, manifest):
    root = tmp_path / 'portable'
    path = root / manifest
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'name': 'portable', 'version': '1.2.0'}))
    (root / 'mcp.json').write_text(json.dumps({'mcpServers': {
        'browser': {'type': 'stdio', 'command': 'npx', 'args': ['@playwright/mcp@latest']}}}))
    assert install(str(root)) == ('portable', 0)
    plugin = plugins.discover()[0]
    assert plugin.mcp_servers['browser']['command'] == ['npx', '@playwright/mcp@latest']
    assert plugins.merged_mcp_servers(config) == {}
    config.set('plugin_trust', {'portable': True})
    assert plugins.merged_mcp_servers(config) == {}
    config.set('mcp_enabled', {'portable__browser': True})
    assert 'portable__browser' in plugins.merged_mcp_servers(config)
