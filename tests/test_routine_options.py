"""MCP servers, skills and models for headless runs and routines."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from eirene.__main__ import main
from eirene.core import paths
from eirene.core.config import Config
from eirene.providers import base
from eirene.scheduling.base import Schedule, Task, load_tasks, parse_names, save_tasks

ANSWER = ('data: {"choices":[{"delta":{"content":"done"}}]}\n\n'
          'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
          '"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
          "data: [DONE]\n\n")
MCP_CALL = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"m1","type":"function",'
            '"function":{"name":"mcp__demo__echo","arguments":"{\\"value\\":\\"hi\\"}"}}]}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
            '"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
            "data: [DONE]\n\n")


@pytest.fixture
def connected():
    config = Config.load()
    config.provider = "chatgpt"
    config.set_provider("chatgpt", api_key="sk-test-key-value", model="gpt-4o")
    config.set("mcp_servers", {"demo": {"command": ["demo-mcp"]},
                               "other": {"command": ["other-mcp"]},
                               "off": {"command": ["off-mcp"]}})
    config.set("mcp_enabled", {"demo": True, "other": True})
    config.save()
    return config


@pytest.fixture
def skills():
    folder = paths.skills_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "release-notes.md").write_text(
        "---\nname: Release notes\ndescription: write release notes\n---\nUse headings.\n")
    (folder / "triage.md").write_text(
        "---\nname: Triage\ndescription: sort incoming issues\n---\nLabel them.\n")
    return ["release-notes", "triage"]


@pytest.fixture
def mcp(monkeypatch):
    """A stand-in MCP manager: records which servers were started and each call."""
    seen = {"started": [], "calls": []}

    class Manager:
        def __init__(self, definitions, sandbox):
            self.definitions, self.errors, self.ready = definitions, [], False
            self.tools = {}

        async def ensure(self):
            self.ready = True
            seen["started"].extend(self.definitions)
            if "demo" in self.definitions:
                self.tools = {"mcp__demo__echo": "demo"}

        def specs(self):
            return [{"name": name, "description": "echo",
                     "parameters": {"type": "object", "properties": {"value": {"type": "string"}}}}
                    for name in self.tools]

        def instruction_block(self):
            return ""

        def owns(self, name):
            return name in self.tools

        async def call(self, name, arguments):
            seen["calls"].append((name, arguments))
            return "echo:" + arguments.get("value", "")

        async def close(self):
            self.ready, self.tools = False, {}

    monkeypatch.setattr("eirene.core.agent.MCPManager", Manager)
    return seen


@pytest.fixture
def model():
    """Reply with an MCP call first, then an answer; keep each request body."""
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        body = MCP_CALL if len(bodies) == 1 else ANSWER
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "text/event-stream"})
    base.set_transport(httpx.MockTransport(handler))
    yield bodies
    base.set_transport(None)


def _tools(body):
    return {tool["function"]["name"] for tool in body.get("tools", [])}


def _system(body):
    return next(m["content"] for m in body["messages"] if m["role"] == "system")


# headless MCP

def test_granted_mcp_server_runs_without_approval(workdir, connected, mcp, model, capsys):
    assert main(["-p", "echo hi", "-C", str(workdir), "--mcp", "demo", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert mcp["started"] == ["demo"]
    assert mcp["calls"] == [("mcp__demo__echo", {"value": "hi"})]
    call = next(c for c in result["tool_calls"] if c["name"] == "mcp__demo__echo")
    assert not call["is_error"]
    assert "mcp__demo__echo" in _tools(model[0])


def test_mcp_all_starts_every_enabled_server(workdir, connected, mcp, model, capsys):
    assert main(["-p", "echo hi", "-C", str(workdir), "--mcp", "all", "--json"]) == 0
    assert sorted(mcp["started"]) == ["demo", "other"]


def test_no_mcp_grant_starts_no_servers(workdir, connected, mcp, model, capsys):
    main(["-p", "echo hi", "-C", str(workdir), "--json"])
    assert mcp["started"] == [] and mcp["calls"] == []
    assert "mcp__demo__echo" not in _tools(model[0])


@pytest.mark.parametrize("name,message", [("ghost", "unknown MCP server"),
                                          ("off", "not enabled")])
def test_bad_mcp_names_are_configuration_errors(workdir, connected, mcp, name, message, capsys):
    assert main(["-p", "hi", "-C", str(workdir), "--mcp", name, "--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert message in result["errors"][0] and mcp["started"] == []


def test_mcp_grant_adds_the_group_to_a_tool_list(workdir, connected, mcp, model, capsys):
    assert main(["-p", "echo hi", "-C", str(workdir), "--tools", "read",
                 "--mcp", "demo", "--json"]) == 0
    names = _tools(model[0])
    assert "mcp__demo__echo" in names and "write_file" not in names
    assert "MCP servers: demo" in "\n".join(str(m["content"]) for m in model[0]["messages"])


def test_task_uses_its_mcp_servers(workdir, connected, mcp, model, capsys):
    save_tasks([Task(id="t1", name="n", prompt="echo", cwd=str(workdir),
                     schedule=Schedule("hourly"), tools=["read", "mcp"],
                     mcp_servers=["demo"])])
    assert main(["--task", "t1"]) == 0
    assert mcp["calls"] == [("mcp__demo__echo", {"value": "hi"})]


# headless skills

@pytest.fixture
def answering():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})
    base.set_transport(httpx.MockTransport(handler))
    yield bodies
    base.set_transport(None)


def test_headless_offers_saved_skills(workdir, connected, skills, answering, capsys):
    assert main(["-p", "hi", "-C", str(workdir)]) == 0
    assert "load_skill" in _tools(answering[0])
    assert "release-notes" in _system(answering[0]) and "triage" in _system(answering[0])


def test_skills_flag_selects_skills(workdir, connected, skills, answering, capsys):
    assert main(["-p", "hi", "-C", str(workdir), "--skills", "triage"]) == 0
    system = _system(answering[0])
    assert "triage" in system and "release-notes" not in system


def test_skills_none_removes_the_skill_tool(workdir, connected, skills, answering, capsys):
    assert main(["-p", "hi", "-C", str(workdir), "--skills", "none"]) == 0
    assert "load_skill" not in _tools(answering[0])


@pytest.mark.usefixtures("trusted_plugins")
def test_skills_flag_can_use_a_skill_disabled_in_settings(workdir, connected, skills, answering, capsys):
    connected.set("skills", {"triage": False})
    connected.save()
    assert main(["-p", "hi", "-C", str(workdir), "--skills", "triage"]) == 0
    assert "triage" in _system(answering[0])


def test_unknown_skill_is_a_configuration_error(workdir, connected, skills, capsys):
    assert main(["-p", "hi", "-C", str(workdir), "--skills", "nope", "--json"]) == 3
    assert "unknown skill" in json.loads(capsys.readouterr().out)["errors"][0]


def test_loading_a_skill_works_headlessly(workdir, connected, skills, capsys):
    call = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"s1","type":"function",'
            '"function":{"name":"load_skill","arguments":"{\\"name\\":\\"triage\\"}"}}]}}]}\n\n'
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}\n\n'
            "data: [DONE]\n\n")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=(call if len(bodies) == 1 else ANSWER).encode(),
                              headers={"content-type": "text/event-stream"})
    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["-p", "triage", "-C", str(workdir), "--skills", "triage", "--json"]) == 0
    finally:
        base.set_transport(None)
    result = json.loads(capsys.readouterr().out)
    assert result["tool_calls"][0] == {**result["tool_calls"][0], "name": "load_skill",
                                       "is_error": False}
    assert "Label them." in json.dumps(bodies[1]["messages"])


def test_task_uses_its_skills(workdir, connected, skills, answering, capsys):
    save_tasks([Task(id="t1", name="n", prompt="go", cwd=str(workdir),
                     schedule=Schedule("hourly"), skills=["release-notes"])])
    assert main(["--task", "t1"]) == 0
    system = _system(answering[0])
    assert "release-notes" in system and "triage" not in system


# records

def test_task_records_round_trip_and_old_records_get_defaults():
    task = Task(id="t", name="n", prompt="p", cwd="/", schedule=Schedule("hourly"),
                mcp_servers=["demo"], skills=["a", "b"], provider="chatgpt", model="gpt-4o")
    again = Task.from_dict(task.to_dict())
    assert again.mcp_servers == ["demo"] and again.skills == ["a", "b"]
    old = Task.from_dict({"id": "t", "name": "n", "prompt": "p", "cwd": "/"})
    assert old.mcp_servers == [] and old.skills is None
    assert old.describe_model() == "the active provider and model at run time"


def test_parse_names():
    assert parse_names("all") == ["*"]
    assert parse_names("none") == [] and parse_names("") == []
    assert parse_names("a, b a") == ["a", "b"]


# /schedule and /routines

class FakeApp:
    def __init__(self, config, workdir, answers, texts=()):
        self.config = config
        self.sandbox = SimpleNamespace(root=workdir)
        self.agent = SimpleNamespace(provider_key="chatgpt", model="gpt-4o")
        self.answers, self.texts = answers, list(texts)
        self.said, self.titles = [], []

    def say(self, text, level="info", **_):
        self.said.append((level, str(text)))

    async def push(self, block):
        pass

    async def ask_choice(self, title, options, **_):
        self.titles.append(title)
        for key, value in self.answers:
            if key in title:
                if callable(value):
                    return value(options)
                assert value in {str(row[0]) for row in options}, (title, value, options)
                return value
        raise AssertionError(f"unexpected question: {title}")

    async def ask_text(self, label, secret=False):
        self.titles.append(label)
        return self.texts.pop(0)


class Engine:
    name, available, supports_signed_out = "fake", True, False

    def validate(self, schedule):
        pass


def test_schedule_chooses_model_mcp_and_skills(workdir, connected, skills, monkeypatch):
    from eirene.commands import routine_options, schedule as schedule_cmd

    class Provider:
        async def models(self):
            return ["gpt-4o", "gpt-4.1-mini"]

        async def close(self):
            pass
    monkeypatch.setattr(routine_options.providers, "build", lambda key, config: Provider())
    app = FakeApp(connected, workdir, [
        ("work directory", "here"), ("which model", "other"), ("provider for", "chatgpt"),
        ("model", "gpt-4.1-mini"), ("access level", "sandboxed"), ("allowed tools", "read"),
        ("MCP servers", "demo"), ("skills", "triage"), ("how often", "hourly"), ("create", "yes"),
    ], texts=["summarise", "nightly"])
    task, _ = asyncio.run(schedule_cmd._build(app, Engine(), ""))
    assert (task.provider, task.model) == ("chatgpt", "gpt-4.1-mini")
    assert task.mcp_servers == ["demo"] and task.tools == ["read", "mcp"]
    assert task.skills == ["triage"]
    assert any("without asking" in title for title in app.titles)


def test_schedule_without_servers_or_skills_skips_those_steps(workdir, monkeypatch):
    from eirene.commands import schedule as schedule_cmd
    config = Config.load()
    app = FakeApp(config, workdir, [
        ("work directory", "here"), ("which model", "current"), ("access level", "sandboxed"),
        ("allowed tools", "all"), ("how often", "hourly"), ("create", "yes"),
    ], texts=["summarise", "nightly"])
    task, _ = asyncio.run(schedule_cmd._build(app, Engine(), ""))
    assert (task.provider, task.model) == ("chatgpt", "gpt-4o")
    assert task.mcp_servers == [] and "mcp" not in task.tools and task.skills is None
    assert not any("MCP" in title or "skills" in title for title in app.titles)


def _saved_task(workdir, **fields):
    task = Task(id="t1", name="nightly", prompt="go", cwd=str(workdir),
                schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o", **fields)
    save_tasks([task])
    return load_tasks()


def _done_after(*steps):
    """Answer the edit menu with each step in turn, then 'done'."""
    order = list(steps)
    return lambda options: order.pop(0) if order else ""


def test_routine_edit_changes_model_mcp_and_skills(workdir, connected, skills, monkeypatch):
    from eirene.commands import routines
    tasks = _saved_task(workdir)
    app = FakeApp(connected, workdir, [
        ("edit nightly", _done_after("model", "mcp", "skills")),
        ("which model", "active"), ("MCP servers", "all"), ("skills", "none"),
    ])
    asyncio.run(routines._edit(app, tasks, tasks[0]))
    saved = load_tasks()[0]
    assert saved.provider == saved.model == ""
    assert saved.mcp_servers == ["*"] and "mcp" in saved.tools
    assert saved.skills == []
    assert sum("applies from the next run" in text for _, text in app.said) == 3


def test_routine_edit_keep_changes_nothing(workdir, connected, skills):
    from eirene.commands import routines
    tasks = _saved_task(workdir, mcp_servers=["demo"], tools=["read", "mcp"], skills=["triage"])
    app = FakeApp(connected, workdir, [
        ("edit nightly", _done_after("model", "mcp", "skills")),
        ("which model", "keep"), ("MCP servers", "keep"), ("skills", "keep"),
    ])
    asyncio.run(routines._edit(app, tasks, tasks[0]))
    saved = load_tasks()[0]
    assert (saved.provider, saved.model) == ("chatgpt", "gpt-4o")
    assert saved.mcp_servers == ["demo"] and saved.skills == ["triage"]
    assert not any("applies" in text for _, text in app.said)


def test_routine_edit_removing_servers_drops_the_mcp_group(workdir, connected):
    from eirene.commands import routines
    tasks = _saved_task(workdir, mcp_servers=["demo"], tools=["read", "edit", "mcp"])
    app = FakeApp(connected, workdir, [("edit nightly", _done_after("mcp")),
                                       ("MCP servers", "none")])
    asyncio.run(routines._edit(app, tasks, tasks[0]))
    saved = load_tasks()[0]
    assert saved.mcp_servers == [] and saved.tools == ["read", "edit"]


def test_routine_edit_full_access_needs_confirmation(workdir, connected):
    from eirene.commands import routines
    tasks = _saved_task(workdir)
    app = FakeApp(connected, workdir, [("edit nightly", _done_after("access")),
                                       ("access level", "full-access"),
                                       ("unattended on your host", "no")])
    asyncio.run(routines._edit(app, tasks, tasks[0]))
    assert load_tasks()[0].access == "sandboxed"


def test_routine_edit_prompt(workdir, connected):
    from eirene.commands import routines
    tasks = _saved_task(workdir)
    app = FakeApp(connected, workdir, [("edit nightly", _done_after("prompt"))],
                  texts=["check the logs"])
    asyncio.run(routines._edit(app, tasks, tasks[0]))
    assert load_tasks()[0].prompt == "check the logs"
