"""Plugin resource boundaries, entry points, and isolated provider-neutral agents."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from eirene.commands import dispatch, lookup
from eirene.core import paths, plugins
from eirene.core.agent import Agent
from eirene.core.delegation import run_tasks, validate_tasks
from eirene.core.errors import ToolError
from eirene.core.plugin_install import install
from eirene.core.plugin_resources import read_resource
from eirene.core.session import Session
from eirene.providers.base import Done, TextDelta, ToolCall, Usage
from eirene.providers.local_profile import LocalProfile


def bundle(tmp_path, name="feature-dev"):
    root = tmp_path / name
    (root / "agents").mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"name": name}))
    (root / "agents/code-explorer.md").write_text("---\ndescription: Trace code\nmodel: sonnet\n---\nTrace the call graph.")
    (root / "references").mkdir()
    (root / "references/rules.md").write_text("Rule one\nRule two\nRule three\n")
    return root


async def test_resources_are_bounded_and_cannot_escape_or_load_disabled_plugins(tmp_path, config):
    install(str(bundle(tmp_path)))
    assert "Rule two" in await read_resource("feature-dev", "references/rules.md", config, offset=1, limit=1)
    assert "Rule one" not in await read_resource("feature-dev", "references/rules.md", config, offset=1, limit=1)
    with pytest.raises(ToolError, match="leaves its directory"):
        await read_resource("feature-dev", "../other/secret", config)
    outside = tmp_path / "secret"
    outside.write_text("secret")
    try:
        (paths.plugins_dir() / "feature-dev/link").symlink_to(outside)
    except OSError:
        pass
    else:
        with pytest.raises(ToolError, match="leaves its directory"):
            await read_resource("feature-dev", "link", config)
    config.set_plugin("feature-dev", False)
    with pytest.raises(ToolError, match="disabled"):
        await read_resource("feature-dev", "references/rules.md", config)


async def test_resource_tool_can_read_installed_absolute_path_without_host_access(tmp_path, config, box):
    from eirene.tools import registry
    install(str(bundle(tmp_path)))
    resource = paths.plugins_dir() / "feature-dev/references/rules.md"
    arguments = {"plugin": "feature-dev", "path": str(resource), "limit": 1}
    assert registry.sandbox_escape("load_plugin_resource", arguments, box) == ""
    result = await registry.execute("load_plugin_resource", arguments, box, config=config)
    assert "Rule one" in result and "Rule two" not in result
    assert not box.full_access


@pytest.mark.parametrize("tier", ["compact", "balanced", "full"])
def test_local_profiles_retain_plugin_instructions_and_tools(tier):
    profile = LocalProfile(tier, 3, 16, 4, 0)
    system = ("Sandbox: /work\nMode is auto.\nOS: Linux\n"
              "Available skills (call load_skill before using one):\n- demo:design\n"
              "Current command instructions:\nReview the payment flow\n"
              "Plugin lifecycle instructions (latest mode changes override earlier defaults):\nKeep it simple\n"
              "Plugin host tools:\nTask -> delegate_tasks\nMCP server instructions:\nActivate project")
    actual = profile.system(system)
    for value in ("demo:design", "Review the payment flow", "Keep it simple", "Task -> delegate_tasks", "Activate project"):
        assert value in actual
    specs = [{"name": name} for name in ("load_skill", "load_plugin_resource", "delegate_tasks", "plan_update", "mcp__browser__navigate")]
    assert profile.tools(specs) == specs


async def test_mcp_entry_command_checks_enablement_and_provider_locally(tmp_path, config):
    root = tmp_path / "playwright"
    root.mkdir()
    (root / "plugin.json").write_text(json.dumps({"name": "playwright"}))
    (root / ".mcp.json").write_text(json.dumps({"playwright": {"command": "npx", "args": ["@playwright/mcp@latest"]}}))
    install(str(root))
    messages, requests = [], []
    async def push(block):
        pass
    async def turn(text, **kwargs):
        requests.append(text)
    app = SimpleNamespace(config=config, turn=None, agent=SimpleNamespace(mode="auto", provider=None),
        say=lambda *a: messages.append(a), push=push, _run_turn=turn)
    assert lookup("playwright", app)
    await dispatch(app, "/playwright https://example.com")
    assert "/mcp" in messages[-1][0]
    assert not requests
    config.set("mcp_enabled", {"playwright__playwright": True})
    app.agent.provider = SimpleNamespace(supports_tools=False, owns_context=False)
    await dispatch(app, "/playwright https://example.com")
    assert "tool-capable" in messages[-1][0]
    app.agent.provider.supports_tools = True
    await dispatch(app, "/playwright https://example.com")
    await app.turn
    assert "Playwright MCP tools" in requests[0] and "https://example.com" in requests[0]


async def test_doctor_reports_missing_dependencies_without_starting_processes(tmp_path, config, monkeypatch):
    from eirene.commands.plugins import run
    install(str(bundle(tmp_path, "superpowers")))
    monkeypatch.setattr("eirene.core.plugin_health.shutil.which", lambda name: None)
    messages = []
    await run(SimpleNamespace(config=config, say=messages.append), "doctor superpowers")
    assert "bash: missing" in messages[0] and "git: missing" in messages[0]


async def test_specialists_use_fresh_contexts_same_provider_and_model(tmp_path, config, box, monkeypatch):
    install(str(bundle(tmp_path)))
    config.set("mode", "auto")
    config.set("execution_isolation", "none")
    received, providers = [], []
    class Provider:
        supports_tools = True
        async def stream(self, messages, model, **kwargs):
            received.append((messages, model, kwargs))
            yield Usage(5, 3)
            yield TextDelta("Found the entry point in main.py:4")
            yield Done("stop")
        async def close(self):
            self.closed = True
    def build(key, child_config):
        assert key == "custom-openai"
        provider = Provider()
        providers.append(provider)
        return provider
    monkeypatch.setattr("eirene.providers.registry.build", build)
    parent = Agent(Session.create(box.root), config, box)
    parent.use(Provider(), "custom-openai", "my-local-model")
    parent.session.add_user("Private conversation that must not leak to reviewers")
    result = json.loads(await run_tasks(parent, [
        {"agent": "feature-dev:code-explorer", "prompt": "Find startup"},
        {"prompt": "Review error handling"},
    ]))
    assert all(r["status"] == "completed" for r in result)
    assert len(providers) == 2 and all(p.closed for p in providers)
    assert len({r["session_id"] for r in result}) == 2
    assert parent._delegated_usage.input_tokens == 10
    for messages, model, kwargs in received:
        assert model == "my-local-model"
        assert "Private conversation" not in str(messages)
        assert all(s["name"] != "delegate_tasks" for s in kwargs["tools"])
        assert "Mode is plan" in kwargs["system"]
    assert "Trace the call graph" in received[0][0][0]["content"]
    await parent.close()


async def test_readonly_specialist_cannot_write_even_with_parent_full_access(tmp_path, config, box, monkeypatch):
    config.set("mode", "auto")
    config.set("permissions", "full-access")
    config.set("execution_isolation", "none")
    class Provider:
        supports_tools = True
        async def stream(self, messages, model, **kwargs):
            if len(messages) == 1:
                yield ToolCall("bad", "write_file", {"path": "forbidden.txt", "content": "oops"})
                yield Done("tool_calls")
            else:
                assert messages[-1]["is_error"] and "plan mode" in messages[-1]["content"]
                yield TextDelta("Write correctly blocked")
                yield Done("stop")
    monkeypatch.setattr("eirene.providers.registry.build", lambda *a: Provider())
    parent = Agent(Session.create(box.root), config, box)
    parent.use(Provider(), "custom-openai", "model")
    result = json.loads(await run_tasks(parent, [{"prompt": "Attempt an unauthorized write"}]))
    assert "blocked" in result[0]["report"]
    assert not (box.root / "forbidden.txt").exists()
    await parent.close()


async def test_delegation_cancellation_closes_every_provider(config, box, monkeypatch):
    config.set("mode", "auto")
    started, closed = [], []
    class Provider:
        supports_tools = True
        async def stream(self, *args, **kwargs):
            started.append(self)
            await asyncio.Event().wait()
            yield Done("stop")
        async def close(self):
            closed.append(self)
    monkeypatch.setattr("eirene.providers.registry.build", lambda *a: Provider())
    parent = Agent(Session.create(box.root), config, box)
    parent.use(Provider(), "custom-openai", "model")
    pending = asyncio.create_task(run_tasks(parent, [{"prompt": "one"}, {"prompt": "two"}]))
    async with asyncio.timeout(5):
        while len(started) < 2:
            await asyncio.sleep(.01)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert set(closed) == set(started)
    await parent.close()


def test_disabled_and_ambiguous_profiles_are_rejected_before_launch(tmp_path, config):
    install(str(bundle(tmp_path)))
    with pytest.raises(ToolError, match="namespaced"):
        validate_tasks([{"agent": "code-explorer", "prompt": "review"}], config)
    config.set_plugin("feature-dev", False)
    with pytest.raises(ToolError, match="disabled"):
        validate_tasks([{"agent": "feature-dev:code-explorer", "prompt": "review"}], config)
    with pytest.raises(ToolError, match="boolean"):
        validate_tasks([{"prompt": "review", "read_only": "false"}], config)


async def test_agent_list_respects_activation_without_changing_mode(tmp_path, config):
    from eirene.core.modes import Mode
    install(str(bundle(tmp_path)))
    messages = []
    app = SimpleNamespace(config=config, agent=SimpleNamespace(mode=Mode.AUTO),
                          say=lambda *a: messages.append(a))
    await dispatch(app, "/agents list")
    assert "feature-dev:code-explorer" in messages[0][0]
    assert "/feature-dev:agent-code-explorer" in messages[0][0]
    assert app.agent.mode is Mode.AUTO
    config.set_plugin("feature-dev", False)
    await dispatch(app, "/agents list")
    assert "no enabled plugin specialists" in messages[-1][0]
