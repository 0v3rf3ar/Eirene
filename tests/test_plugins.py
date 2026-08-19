"""Declarative plugins, selective skills, and lifecycle hooks."""

from __future__ import annotations

import json

import pytest

from eirene.core import hooks, paths, plugins, skills
from eirene.core.config import Config
from eirene.core.errors import ToolError


def make_plugin(name="demo"):
    root = paths.plugins_dir() / name
    root.mkdir(parents=True)
    (root / "review.md").write_text(
        "---\nname: Review carefully\ndescription: Check a completed change.\n---\n"
        "Run tests and inspect the diff.\n", encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({
        "version": 1, "name": name, "description": "demo plugin",
        "skills": ["review.md"],
        "hooks": {"before_tool": ["echo before >> hook.log"],
                  "after_tool": ["echo after >> hook.log"]},
        "mcp_servers": {"example": {"command": ["example-mcp"]}},
    }), encoding="utf-8")
    return root


def test_plugin_manifest_contributes_namespaced_skills():
    make_plugin()
    found = plugins.discover()
    assert [plugin.name for plugin in found] == ["demo"]
    skill = next(item for item in skills.discover() if item.name == "demo:review")
    assert "inspect the diff" in skills.load(skill)
    catalog = skills.catalog_block([skill])
    assert "demo:review" in catalog
    assert "Run tests" not in catalog


def test_plugin_paths_cannot_escape_the_plugin_directory(tmp_path):
    root = paths.plugins_dir() / "bad"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({
        "name": "bad", "skills": ["../../outside.md"],
    }), encoding="utf-8")
    assert plugins.discover()[0].skills == []


def test_disabled_plugin_does_not_contribute_hooks_or_mcp():
    make_plugin()
    config = Config.load()
    config.set_plugin("demo", False)
    assert plugins.merged_hooks(config)["before_tool"] == []
    assert plugins.merged_mcp_servers(config) == {}


async def test_hooks_run_with_tool_context(workdir, box):
    make_plugin()
    config = Config.load()
    before = await hooks.run("before_tool", "write_file", box, config)
    after = await hooks.run("after_tool", "write_file", box, config)
    assert len(before) == len(after) == 1
    assert (workdir / "hook.log").read_text().splitlines() == ["before", "after"]


async def test_a_failing_hook_stops_the_operation(box):
    config = Config.load()
    config.set("hooks", {"before_tool": ["exit 7"]})
    with pytest.raises(ToolError, match="hook failed"):
        await hooks.run("before_tool", "write_file", box, config)


async def test_plan_mode_agent_never_runs_mutating_hooks(workdir):
    from eirene.core.agent import Agent
    from eirene.core.modes import Mode
    from eirene.core.session import Session
    from eirene.providers.base import Done, TextDelta, ToolCall
    from eirene.tools.sandbox import Sandbox

    class Provider:
        supports_tools = True
        calls = 0
        async def stream(self, messages, model, **kwargs):
            self.calls += 1
            if self.calls == 1:
                yield ToolCall("one", "list_dir", {"path": "."})
                yield Done("tool_use")
            else:
                yield TextDelta("done")
                yield Done("stop")

    config = Config.load()
    config.set("hooks", {"before_tool": ["touch hook-ran"]})
    agent = Agent(Session.create(workdir), config, Sandbox(workdir))
    agent.mode = Mode.PLAN
    agent.use(Provider(), "test", "model")
    [event async for event in agent.run("inspect")]
    await agent.close()
    assert not (workdir / "hook-ran").exists()
