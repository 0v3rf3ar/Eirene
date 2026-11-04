"""Trust is one switch for a whole plugin: nothing works before it, everything after it."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from eirene.commands import dispatch, lookup, plugin_commands
from eirene.commands.plugins import run
from eirene.core import paths, plugin_install, plugin_resources, plugins, skills
from eirene.core.config import Config
from eirene.core.errors import ToolError
from eirene.core.plugin_runtime import PluginRuntime


def whole_plugin(root):
    """One plugin with every kind of thing a plugin can add."""
    (root / "skills/guide").mkdir(parents=True)
    (root / "skills/guide/SKILL.md").write_text("---\ndescription: Guide\n---\nGuide.")
    (root / "commands").mkdir()
    (root / "commands/go.md").write_text("Go.")
    (root / "agents").mkdir()
    (root / "agents/helper.md").write_text("---\ndescription: Helper\n---\nHelp.")
    (root / "hooks").mkdir()
    (root / "hooks/hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "echo started"}]}]}}))
    (root / ".mcp.json").write_text(json.dumps({"mcpServers": {"srv": {"command": "tool-server"}}}))
    (root / "plugin.json").write_text(json.dumps({"name": "whole", "description": "All of it"}))
    return root


def working(config):
    """Each kind of thing, and whether it works now."""
    names = {command.name for command in plugin_commands.commands(config)}
    return {
        "skill": skills.apply_config(skills.discover(), config)[0].enabled,
        "skill command": "guide" in names,
        "command": "go" in names,
        "agent": "whole:helper" in plugin_resources.agent_definitions(config),
        "guidance": bool(plugin_resources.guidance(config)),
        "hook": plugins.executable_enabled(plugins.discover()[0], config),
        "mcp": "whole__srv" in plugins.merged_mcp_servers(config),
    }


def app_for(config, *answers):
    said = []
    return SimpleNamespace(config=config, turn=None, said=said, say=lambda text, *a: said.append(str(text)),
                           ask_choice=AsyncMock(side_effect=list(answers) or [None]),
                           _save_config=config.save, agent=SimpleNamespace(reload_skills=lambda: None))


@pytest.fixture
def installed(tmp_path):
    plugin_install.install(str(whole_plugin(tmp_path / "whole")))


def test_nothing_works_before_trust(installed, config):
    assert not any(working(config).values()), working(config)


async def test_one_trust_turns_on_all_of_it_with_no_refresh(installed, config):
    app = app_for(config, "yes")
    await run(app, "trust whole")
    assert all(working(config).values()), working(config)
    assert "on now" in app.said[-1]
    # It is saved, so a new session starts with it on.
    assert all(working(Config.load()).values())


async def test_declining_leaves_all_of_it_off(installed, config):
    await run(app_for(config, "no"), "trust whole")
    assert not any(working(config).values())


async def test_untrust_turns_all_of_it_off_and_trust_brings_all_of_it_back(installed, config):
    await run(app_for(config, "yes"), "trust whole")
    await run(app_for(config), "untrust whole")
    assert not any(working(config).values())
    await run(app_for(config, "yes"), "trust whole")
    assert all(working(config).values())


async def test_trust_brings_back_a_server_turned_off_earlier(installed, config):
    config.set("plugin_trust", {"whole": True})
    config.set("mcp_enabled", {"whole__srv": False})
    assert not working(config)["mcp"]
    config.set("plugin_trust", {})
    await run(app_for(config, "yes"), "trust whole")
    assert working(config)["mcp"]


async def test_untrusted_hooks_do_not_run(installed, config, box):
    config.set("execution_isolation", "none")
    runtime = PluginRuntime("untrusted")
    await runtime.submit("hello", box, config)
    assert not runtime.started


async def test_resources_are_closed_until_trusted(installed, config):
    with pytest.raises(ToolError, match="untrusted"):
        await plugin_resources.read_resource("whole", "skills/guide/SKILL.md", config)
    config.set("plugin_trust", {"whole": True})
    assert "Guide." in await plugin_resources.read_resource("whole", "skills/guide/SKILL.md", config)


def test_a_folder_placed_by_hand_gets_no_exception(config):
    # This used to skip trust, because only the installer marked plugins as imported.
    root = paths.plugins_dir() / "hand"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({
        "name": "hand", "version": 1, "hooks": {"before_tool": ["echo hook"]},
        "lifecycle": {"SessionStart": [{"command": "echo start", "matcher": "", "timeout": 5}]},
        "mcp_servers": {"s": {"command": ["x"]}}}))
    plugin = plugins.discover()[0]
    assert not plugins.executable_enabled(plugin, config)
    assert plugins.merged_hooks(config)["before_tool"] == []
    assert plugins.merged_mcp_servers(config) == {}
    config.set("plugin_trust", {"hand": True})
    assert plugins.merged_hooks(config)["before_tool"] == ["echo hook"]
    assert set(plugins.merged_mcp_servers(config)) == {"s"}


def test_shipped_plugins_need_trust_too(config):
    plugin_install.install("arena")
    assert lookup("arena", SimpleNamespace(config=config)) is None
    config.set("plugin_trust", {"arena": True})
    assert lookup("arena", SimpleNamespace(config=config))


def test_your_own_skills_need_no_trust(config):
    (paths.skills_dir() / "mine.md").write_text("# Mine")
    (paths.skills_dir() / "group").mkdir()
    (paths.skills_dir() / "group/one.md").write_text("# One")
    assert all(skill.enabled for skill in skills.apply_config(skills.discover(), config))
    assert "mine" in {command.name for command in plugin_commands.commands(config)}


async def test_disable_still_works_on_a_trusted_plugin(installed, config):
    config.set("plugin_trust", {"whole": True})
    config.set_plugin("whole", False)
    assert not any(value for key, value in working(config).items() if key != "hook")
    assert config.plugin_trusted("whole")


@pytest.mark.parametrize("typed", ["/go", "/guide", "/whole", "/whole:go"])
async def test_typing_its_command_says_how_to_turn_it_on(installed, config, typed):
    app = app_for(config)
    await dispatch(app, typed)
    assert "/plugins trust whole" in app.said[-1]


async def test_install_says_it_is_off(tmp_path, config):
    app = app_for(config)
    await run(app, "install " + str(whole_plugin(tmp_path / "whole")))
    assert "stays off until you trust it" in app.said[-1] and "/plugins trust whole" in app.said[-1]
    assert not config.get("plugin_trust")
