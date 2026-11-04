"""Headless runs and the command line."""

from __future__ import annotations

import json
import sys

import httpx
import pytest

from eirene.__main__ import build_parser, main
from eirene.core.config import Config
from eirene.core.session import list_sessions
from eirene.providers import base

ANSWER = ('data: {"choices":[{"delta":{"content":"done"}}]}\n\n'
          'data: {"choices":[{"delta":{},"finish_reason":"stop"}],'
          '"usage":{"prompt_tokens":5,"completion_tokens":2}}\n\n'
          "data: [DONE]\n\n")


@pytest.fixture
def connected():
    config = Config.load()
    config.provider = "chatgpt"
    config.set_provider("chatgpt", api_key="sk-test-key-value", model="gpt-4o")
    config.save()
    return config


@pytest.fixture
def answering():
    def handler(request):
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})
    base.set_transport(httpx.MockTransport(handler))
    yield
    base.set_transport(None)


def test_parser_defaults():
    args = build_parser().parse_args([])
    assert args.directory == "." and args.mode == "auto"
    assert args.prompt is None and args.task is None


def test_parser_reads_the_flags():
    args = build_parser().parse_args(["-p", "hi", "-C", "/tmp", "--mode", "plan",
                                      "--provider", "ollama", "--model", "x"])
    assert args.prompt == "hi" and args.directory == "/tmp"
    assert args.mode == "plan" and args.provider == "ollama"


def test_missing_directory_is_reported(capsys):
    assert main(["-p", "hi", "-C", "/no/such/place"]) == 2
    assert "no such directory" in capsys.readouterr().err


def test_prompt_run_prints_the_answer(workdir, connected, answering, capsys):
    code = main(["-p", "say done", "-C", str(workdir)])
    captured = capsys.readouterr()
    assert code == 0
    assert "done" in captured.out


def test_prompt_run_logs_a_session(workdir, connected, answering, capsys):
    main(["-p", "say done", "-C", str(workdir)])
    capsys.readouterr()
    sessions = list_sessions()
    assert sessions and sessions[0]["sandbox"] == str(workdir)


def test_prompt_run_without_a_provider(workdir, capsys):
    assert main(["-p", "hi", "-C", str(workdir)]) == 3
    assert "/connect" in capsys.readouterr().err


def test_prompt_run_reports_a_bad_key(workdir, connected, capsys):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "nope"}},
                              headers={"content-type": "application/json"})
    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["-p", "hi", "-C", str(workdir)]) == 4
        assert "rejected" in capsys.readouterr().err
    finally:
        base.set_transport(None)


def test_unknown_task_is_reported(capsys):
    assert main(["--task", "nope"]) == 1
    assert "no task" in capsys.readouterr().err


def test_task_with_a_missing_directory(tmp_path, capsys):
    from eirene.scheduling.base import Schedule, Task, save_tasks
    gone = tmp_path / "deleted"
    save_tasks([Task(id="t1", name="n", prompt="do it", cwd=str(gone),
                     schedule=Schedule("hourly"))])
    assert main(["--task", "t1"]) == 1
    assert "working directory is gone" in capsys.readouterr().err


def test_task_runs_headlessly(workdir, connected, answering, capsys):
    from eirene.scheduling.base import Schedule, Task, save_tasks
    save_tasks([Task(id="t1", name="nightly", prompt="build it", cwd=str(workdir),
                     schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o")])
    assert main(["--task", "t1"]) == 0
    assert "done" in capsys.readouterr().out


def test_task_prompt_tells_the_model_it_is_unattended(workdir, connected):
    from eirene.core.prompt import TASK_PROMPT
    from eirene.scheduling.base import Schedule, Task, save_tasks
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})

    base.set_transport(httpx.MockTransport(handler))
    save_tasks([Task(id="t1", name="n", prompt="build it", cwd=str(workdir),
                     schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o")])
    try:
        main(["--task", "t1"])
        user = [m for m in seen["body"]["messages"] if m["role"] == "user"][0]
        assert TASK_PROMPT.strip().splitlines()[0] in user["content"]
        assert "build it" in user["content"]
    finally:
        base.set_transport(None)


def test_resume_takes_an_optional_id():
    assert build_parser().parse_args([]).resume is None
    assert build_parser().parse_args(["--resume"]).resume == ""
    assert build_parser().parse_args(["--resume", "abc"]).resume == "abc"


def test_continue_flag_is_exclusive_with_resume():
    assert not build_parser().parse_args([]).continue_session
    assert build_parser().parse_args(["--continue"]).continue_session
    with pytest.raises(SystemExit) as caught:
        build_parser().parse_args(["--continue", "--resume"])
    assert caught.value.code == 2


@pytest.mark.parametrize("terminal", [True, False])
def test_continue_selects_most_recent_workspace_session_without_menu(
        workdir, tmp_path, monkeypatch, capsys, terminal):
    import os
    from eirene import __main__ as cli
    from eirene.core.session import Session

    recent = Session.create(workdir)
    recent.add_user("updated conversation")
    recent.close()
    older = Session.create(workdir)
    older.add_user("older conversation")
    older.close()
    elsewhere = Session.create(tmp_path)
    elsewhere.add_user("different workspace")
    elsewhere.close()
    for saved, stamp in [(older, 100), (recent, 200), (elsewhere, 300)]:
        os.utime(saved.path, (stamp, stamp))

    opened = []
    monkeypatch.setattr(sys.stdout, "isatty", lambda: terminal, raising=False)
    monkeypatch.setattr(cli, "open_session",
                        lambda box, resume: opened.append((box, resume)) or 17)
    monkeypatch.setattr(cli, "pick_session",
                        lambda box: pytest.fail("continue must never open the picker"))

    result = main(["--continue", "-C", str(workdir)])
    captured = capsys.readouterr()
    assert captured.out == ""
    if terminal:
        assert result == 17
        assert opened == [(workdir.resolve(), recent.id)]
    else:
        assert result == 2
        assert opened == []
        assert "needs a terminal" in captured.err


def test_continue_with_nothing_saved(workdir, monkeypatch, capsys):
    from eirene import __main__ as cli

    monkeypatch.setattr(cli, "pick_session",
                        lambda box: pytest.fail("continue must never open the picker"))
    assert main(["--continue", "-C", str(workdir)]) == 0
    assert "no saved sessions" in capsys.readouterr().out


def test_bare_resume_lists_this_directory(workdir, tmp_path, capsys):
    from eirene.core.session import Session
    other = tmp_path / "elsewhere"
    other.mkdir()
    mine = Session.create(workdir)
    mine.add_user("hello")
    mine.close()
    theirs = Session.create(other)
    theirs.add_user("hello")
    theirs.close()

    assert main(["--resume", "-C", str(workdir)]) == 0
    out = capsys.readouterr().out
    assert mine.id in out
    assert theirs.id not in out
    assert "1 turn" in out


def test_bare_resume_with_nothing_saved(workdir, capsys):
    assert main(["--resume", "-C", str(workdir)]) == 0
    assert "no saved sessions" in capsys.readouterr().out


def test_version_comes_from_pyproject():
    import re
    from pathlib import Path
    from eirene import __version__

    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    body = manifest.read_text(encoding="utf-8").split("[project]", 1)[1]
    declared = re.search(r'^\s*version\s*=\s*"([^"]+)"', body, re.M).group(1)
    assert __version__ == declared


@pytest.mark.parametrize("flag", ["-v", "--version"])
def test_version_flag(flag, capsys):
    from eirene import __version__
    with pytest.raises(SystemExit) as exit_info:
        main([flag])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"eirene {__version__}"


def test_bare_resume_shows_names_without_a_terminal(workdir, capsys):
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("fix the ollama provider please")
    saved.close()

    assert main(["--resume", "-C", str(workdir)]) == 0
    out = capsys.readouterr().out
    assert "Fix the ollama provider please" in out
    assert saved.id in out


def test_bare_resume_opens_the_chosen_session(workdir, monkeypatch):
    from eirene import __main__ as cli
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("named chat")
    saved.close()

    seen = {}

    def fake_open(box, resume):
        seen["resume"] = resume
        return 0

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "open_session", fake_open)
    import eirene.ui.sessions as chooser
    monkeypatch.setattr(chooser, "choose_session", lambda rows, box: rows[0]["id"])

    assert cli.pick_session(workdir) == 0
    assert seen["resume"] == saved.id


def test_session_picker_metadata_uses_aligned_columns():
    from eirene.ui.sessions import options

    rows = [
        {"id": "12345678-long", "name": "Short", "mtime": 1, "turns": 2},
        {"id": "abcdef01-long", "name": "A much longer name", "mtime": 1,
         "turns": 120},
    ]
    choices = options(rows)
    rendered = [f"{row[1]}  {row[2]}" for row in choices]
    assert rendered[0].index("12345678") == rendered[1].index("abcdef01")
    assert rendered[0].index("turns") == rendered[1].index("turns")


def test_choosing_nothing_just_leaves(workdir, monkeypatch):
    from eirene import __main__ as cli
    from eirene.core.session import Session

    saved = Session.create(workdir)
    saved.add_user("named chat")
    saved.close()

    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "open_session", lambda box, resume: 99)
    import eirene.ui.sessions as chooser
    monkeypatch.setattr(chooser, "choose_session", lambda rows, box: "")
    assert cli.pick_session(workdir) == 0


def test_json_answer_reports_input_identity_and_usage(workdir, connected, answering, capsys):
    assert main(["-p", "say done", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["input"] == "say done"
    assert result["output"] == "done"
    assert result["provider"] == "chatgpt" and result["model"] == "gpt-4o"
    assert result["input_tokens"] == 5 and result["output_tokens"] == 2
    assert result["status"] == "completed" and result["exit_code"] == 0


def test_json_configuration_failure_is_still_a_result(workdir, capsys):
    assert main(["-p", "hi", "-C", str(workdir), "--json"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["error_kind"] == "config" and result["exit_code"] == 3
    assert result["input"] == "hi" and result["output"] == ""
    assert result["status"] == "failed" and result["output_tokens"] == 0
    assert result["errors"]


def test_provider_discovery_needs_no_connection(workdir, capsys):
    assert main(["--list-providers", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert any(row["provider"] == "chatgpt" for row in result["data"])
    assert result["output_tokens"] == 0


def test_configured_provider_discovery_does_not_expose_credentials(workdir, connected, capsys):
    assert main(["--configured-providers", "-C", str(workdir), "--json"]) == 0
    captured = capsys.readouterr()
    result = json.loads(captured.out)
    assert [row["provider"] for row in result["data"]] == ["chatgpt"]
    assert result["data"][0]["active"] is True
    assert "sk-test" not in captured.out + captured.err


@pytest.mark.parametrize("arguments", [["--list-models", "openai"], ["-p", "/models openai"],
                                       ["-p", "/model"]])
def test_headless_model_discovery(workdir, connected, capsys, arguments):
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(
        200, json={"data": [{"id": "model-a"}, {"id": "model-b"}]})))
    try:
        assert main([*arguments, "-C", str(workdir), "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["provider"] == "chatgpt"
        assert result["data"] == ["model-a", "model-b"]
        assert Config.load().provider_config("chatgpt")["model"] == "gpt-4o"
    finally:
        base.set_transport(None)


def test_headless_slash_help_without_provider(workdir, capsys):
    assert main(["-p", "/help", "-C", str(workdir)]) == 0
    assert "/review" in capsys.readouterr().out


def test_headless_slash_model_sets_saved_model(workdir, connected, capsys):
    assert main(["-p", "/model model-new", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model"] == "model-new" and result["output_tokens"] == 0
    assert Config.load().provider_config("chatgpt")["model"] == "model-new"


def test_headless_choices_are_explicit_and_never_default_to_approval(workdir, capsys):
    assert main(["-p", "/permissions", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert {row["key"] for row in result["data"]} == {"sandboxed", "full-access"}
    assert Config.load().get("permissions") == "sandboxed"
    assert main(["-p", "/plan clear", "-C", str(workdir), "--json"]) == 1
    assert "--choice" in json.loads(capsys.readouterr().out)["errors"][0]


def test_headless_choice_updates_setting(workdir, capsys):
    assert main(["-p", "/agents", "--choice", "plan", "-C", str(workdir)]) == 0
    capsys.readouterr()
    assert Config.load().mode == "plan"


def test_headless_unknown_slash_command_fails_without_model_request(workdir, capsys):
    assert main(["-p", "/nonexistent", "-C", str(workdir), "--json"]) == 1
    assert "unknown command" in json.loads(capsys.readouterr().out)["errors"][0]


def test_headless_review_waits_for_answer_and_reports_usage(workdir, connected, answering, capsys):
    (workdir / ".git").mkdir()
    assert main(["-p", "/review", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["input"] == "/review" and result["output"] == "done"
    assert result["output_tokens"] == 2


def test_json_timeout_retains_partial_answer(workdir, connected, monkeypatch, capsys):
    import asyncio
    from eirene.core.agent import Agent, Answer
    from eirene.headless import run_prompt

    async def slow(self, text, **kwargs):
        yield Answer("partial")
        await asyncio.sleep(10)

    monkeypatch.setattr(Agent, "run", slow)
    assert run_prompt("hi", workdir, json_output=True, task_timeout=0.01) == 124
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "timeout" and result["output"] == "partial"


@pytest.mark.usefixtures("trusted_plugins")
def test_headless_plugin_command_expands_and_awaits_turn(workdir, connected, capsys):
    from eirene.core import paths

    root = paths.plugins_dir() / "demo"
    root.mkdir(parents=True)
    (root / "plugin.json").write_text(json.dumps({"version": 1, "name": "demo",
                                                 "commands": ["explain.md"]}))
    (root / "explain.md").write_text("Explain $ARGUMENTS without using tools.")
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})

    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["-p", "/demo:explain widgets", "-C", str(workdir), "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["input"] == "/demo:explain widgets" and result["output"] == "done"
        assert result["output_tokens"] == 2
        assert "Explain widgets" in str(seen["body"])
    finally:
        base.set_transport(None)


def test_headless_rich_command_output_needs_no_ui(workdir, capsys):
    assert main(["-p", "/plan", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["output"] and result["output_tokens"] == 0


def test_headless_connect_reuses_saved_connection(workdir, connected, capsys):
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(
        200, json={"data": [{"id": "gpt-4o"}]})))
    try:
        assert main(["-p", "/connect openai", "-C", str(workdir), "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["provider"] == "chatgpt" and result["model"] == "gpt-4o"
        assert Config.load().provider == "chatgpt"
    finally:
        base.set_transport(None)


def test_task_json_is_one_final_result(workdir, connected, answering, capsys):
    from eirene.scheduling.base import Schedule, Task, save_tasks

    save_tasks([Task(id="t1", name="nightly", prompt="build it", cwd=str(workdir),
                     schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o")])
    assert main(["--task", "t1", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["input"] == "build it" and result["output"] == "done"
    assert result["output_tokens"] == 2 and result["attempts"] == 1


def test_unknown_task_json_is_a_failure(capsys):
    assert main(["--task", "unknown", "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed" and result["task_id"] == "unknown"


def test_task_json_retries_emit_only_final_attempt(workdir, connected, monkeypatch, capsys):
    from eirene import headless
    from eirene.scheduling.base import Schedule, Task, save_tasks

    monkeypatch.setattr(headless.time, "sleep", lambda seconds: None)
    requests = []

    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(401, json={"error": {"message": "rejected"}})
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})

    save_tasks([Task(id="t1", name="retry", prompt="try it", cwd=str(workdir),
                     schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o",
                     retries=1, retry_delay=0)])
    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["--task", "t1", "--json"]) == 0
        result = json.loads(capsys.readouterr().out)
        assert result["output"] == "done" and result["attempts"] == 2
        assert result["errors"] == [] and result["output_tokens"] == 2
    finally:
        base.set_transport(None)


@pytest.mark.parametrize('failed', [False, True])
def test_read_output_events_are_silent(capsys, failed):
    from eirene.core.agent import ToolFinished, ToolStarted
    from eirene.headless import _emit

    _emit(ToolStarted('page', 'read_output', 'internal artifact', 'read'), False)
    _emit(ToolFinished('page', 'read_output', 'internal artifact', 'internal result', failed, 0), False)
    captured = capsys.readouterr()
    assert captured.out == captured.err == ''


def test_task_only_offers_the_granted_tools(workdir, connected):
    from eirene.scheduling.base import Schedule, Task, save_tasks
    from eirene.scheduling.history import finished_runs, load_output
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=ANSWER.encode(),
                              headers={"content-type": "text/event-stream"})

    base.set_transport(httpx.MockTransport(handler))
    save_tasks([Task(id="t1", name="n", prompt="look around", cwd=str(workdir),
                     schedule=Schedule("hourly"), provider="chatgpt", model="gpt-4o",
                     tools=["read"])])
    try:
        assert main(["--task", "t1"]) == 0
        names = {tool["function"]["name"] for tool in seen["body"].get("tools", [])}
        assert "read_file" in names
        assert not names & {"write_file", "edit_file", "run_command", "web_fetch",
                            "delegate_tasks", "request_full_access"}
        item = finished_runs("t1")[0]
        assert load_output("t1", item["run"])["output"].strip() == "done"
    finally:
        base.set_transport(None)


def test_answers_around_a_tool_call_stay_separate_paragraphs():
    from eirene.core.agent import Answer, ToolFinished, ToolStarted
    from eirene.headless import RunOutput
    output = RunOutput("x", True, True)
    output.event(Answer("Reading the file."))
    output.event(ToolStarted("t1", "read", "notes.txt", "read"))
    output.event(Answer("## Results"))
    output.event(Answer(" all good"))
    assert output.result["output"] == "Reading the file.\n\n## Results all good"


# --- launch limits, stdin, streaming and exit codes -------------------------

TOOL_CALL = ('data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","type":"function",'
             '"function":{"name":"write_file","arguments":"{\\"path\\":\\"out.txt\\",'
             '\\"content\\":\\"hi\\"}"}}]}}]}\n\n'
             'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],'
             '"usage":{"prompt_tokens":50,"completion_tokens":10}}\n\n'
             "data: [DONE]\n\n")


@pytest.fixture
def recording():
    """Answer each request, first with a file write, and keep the request bodies."""
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        body = TOOL_CALL if len(bodies) == 1 else ANSWER
        return httpx.Response(200, content=body.encode(),
                              headers={"content-type": "text/event-stream"})
    base.set_transport(httpx.MockTransport(handler))
    yield bodies
    base.set_transport(None)


def _user_text(body):
    return "\n".join(str(m.get("content")) for m in body["messages"] if m["role"] == "user")


def _model_text(body):
    return "\n".join(str(m.get("content")) for m in body["messages"])


def test_run_flags_need_a_prompt(workdir, capsys):
    assert main(["-C", str(workdir), "--timeout", "5"]) == 2
    assert "--timeout" in capsys.readouterr().err
    assert main(["--task", "t1", "--quiet"]) == 2


def test_tools_flag_uses_the_schedule_format(capsys):
    args = build_parser().parse_args(["-p", "x", "--tools", "shell, files"])
    assert args.tools == ["read", "edit", "commands"]
    with pytest.raises(SystemExit):
        build_parser().parse_args(["-p", "x", "--tools", "rootkit"])
    assert "unknown tool group" in capsys.readouterr().err


@pytest.mark.parametrize("flag", ["--timeout", "--max-steps", "--max-tokens"])
def test_limits_must_be_positive(flag, capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["-p", "x", flag, "0"])


def test_json_and_stream_json_are_exclusive(workdir, capsys):
    assert main(["-p", "x", "-C", str(workdir), "--json", "--stream-json"]) == 2


def test_tools_flag_limits_the_offered_tools(workdir, connected, recording, capsys):
    assert main(["-p", "look", "-C", str(workdir), "--tools", "read"]) == 0
    names = {tool["function"]["name"] for tool in recording[0].get("tools", [])}
    assert "read_file" in names
    assert not names & {"write_file", "edit_file", "run_command", "web_fetch",
                        "delegate_tasks", "request_full_access"}
    assert "Allowed tools: read" in _model_text(recording[0])
    # The saved session keeps the user's words, not the access note.
    from eirene.core import paths
    log = (paths.sessions_dir() / f"{list_sessions()[0]['id']}.jsonl").read_text()
    assert "look" in log and "Allowed tools" not in log


def test_restricted_tools_fail_closed_on_a_native_tool_provider(workdir, connected, monkeypatch):
    from eirene.core.agent import Agent, Failed
    from eirene.headless import RunOutput, _drive
    import asyncio

    class Native:
        owns_context, supports_tools = True, False

    real_use = Agent.use

    def use(self, provider, key, model):
        real_use(self, provider, key, model)
        self.provider = Native()
    monkeypatch.setattr(Agent, "use", use)
    output = RunOutput("x", True, True)
    code = asyncio.run(_drive("x", workdir, "", "", "auto", True, output=output,
                              tool_groups=["read"]))
    assert code == 1 and output.result["error_kind"] == "config"
    assert "cannot be enforced" in output.result["errors"][0]


def test_json_result_lists_tools_files_and_duration(workdir, connected, recording, capsys):
    assert main(["-p", "write it", "-C", str(workdir), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert [call["name"] for call in result["tool_calls"]] == ["write_file"]
    assert result["tool_call_count"] == 1
    assert result["files_edited"] == ["out.txt"]
    assert result["input_tokens"] == 55 and result["output_tokens"] == 12
    assert result["duration_seconds"] >= 0 and result["session"]
    assert result["cost_usd"] is None


def test_json_reports_cost_when_prices_are_configured(workdir, connected, answering, capsys):
    connected.set("model_costs", {"gpt-4o": {"input_per_million": 1_000_000,
                                             "output_per_million": 2_000_000}})
    connected.save()
    assert main(["-p", "hi", "-C", str(workdir), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["cost_usd"] == 9.0


def test_stream_json_emits_events_then_the_result(workdir, connected, recording, capsys):
    assert main(["-p", "write it", "-C", str(workdir), "--stream-json"]) == 0
    captured = capsys.readouterr()
    events = [json.loads(line) for line in captured.out.splitlines()]
    kinds = [event["type"] for event in events]
    assert kinds[0] == "start" and kinds[-1] == "result"
    assert {"tool_start", "tool_end", "text", "turn_done"} <= set(kinds)
    assert events[-1]["output"] == "done" and events[-1]["exit_code"] == 0
    assert "write_file" not in captured.err


def test_quiet_hides_tool_activity(workdir, connected, recording, capsys):
    assert main(["-p", "write it", "-C", str(workdir), "-q"]) == 0
    captured = capsys.readouterr()
    assert "done" in captured.out and "write_file" not in captured.err


def test_max_steps_stops_the_turn_as_incomplete(workdir, connected, recording, capsys):
    assert main(["-p", "write it", "-C", str(workdir), "--max-steps", "1", "--json"]) == 6
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete" and result["error_kind"] == "incomplete"
    assert "1 steps" in result["errors"][0]
    assert len(recording) == 1


def test_max_tokens_stops_before_running_more_tools(workdir, connected, recording, capsys):
    assert main(["-p", "write it", "-C", str(workdir), "--max-tokens", "40", "--json"]) == 6
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "incomplete" and "token limit" in result["errors"][0]
    assert result["tool_calls"] == [] and not (workdir / "out.txt").exists()


def test_timeout_flag_is_used(workdir, connected, monkeypatch, capsys):
    from eirene import headless
    seen = {}

    def fake(text, cwd, **kwargs):
        seen.update(kwargs)
        return 0
    monkeypatch.setattr(headless, "run_prompt", fake)
    assert main(["-p", "hi", "-C", str(workdir), "--timeout", "42"]) == 0
    assert seen["task_timeout"] == 42


def test_network_failure_has_its_own_exit_code(workdir, connected, monkeypatch, capsys):
    from eirene.core.agent import Agent
    from eirene.core.errors import ConnectionFailed
    monkeypatch.setattr(Agent, "retry_attempts", property(lambda self: 1))

    def handler(request):
        raise httpx.ConnectError("refused", request=request)
    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["-p", "hi", "-C", str(workdir), "--json"]) == 5
        result = json.loads(capsys.readouterr().out)
        assert result["error_kind"] == "network"
    finally:
        base.set_transport(None)


def test_error_kinds():
    from eirene.core.errors import (AuthError, ConfigError, ConnectionFailed, ModelNotFound,
                                    ProviderError, RateLimitError, ToolError, error_kind)
    assert error_kind(AuthError()) == "auth"
    assert error_kind(ModelNotFound("x")) == error_kind(ConfigError("x")) == "config"
    assert error_kind(ConnectionFailed("h")) == error_kind(RateLimitError()) == "network"
    assert error_kind(ProviderError("bad", status=503)) == "network"
    assert error_kind(ProviderError("bad", status=400)) == "provider"
    assert error_kind(ToolError("x")) == "tool"
    try:
        try:
            raise ConnectionFailed("h")
        except ProviderError as inner:
            raise ProviderError("cannot reach h. try later") from inner
    except ProviderError as outer:
        assert error_kind(outer) == "network"
    assert error_kind(ValueError()) == "failed"


class _Pipe:
    """A stand-in stdin: piped bytes, or a pipe that stays open with nothing in it."""

    def __init__(self, data=None):
        import io
        import threading
        self.data, self.blocked = data, threading.Event()
        self.buffer = io.BytesIO(data) if data is not None else self

    def isatty(self):
        return False

    def read1(self, size):
        self.blocked.wait()
        return b""


def test_piped_input_is_added_after_the_prompt(monkeypatch):
    from eirene import __main__ as cli
    monkeypatch.setattr(sys, "stdin", _Pipe(b"diff --git a b\n"))
    assert cli.read_stdin("review this") == "review this\n\n<stdin>\ndiff --git a b\n</stdin>"


def test_dash_reads_the_whole_prompt_from_stdin(monkeypatch):
    from eirene import __main__ as cli
    monkeypatch.setattr(sys, "stdin", _Pipe(b"  explain the project\n"))
    assert cli.read_stdin("-") == "explain the project"


def test_open_unused_stdin_does_not_hang(monkeypatch):
    from eirene import __main__ as cli
    pipe = _Pipe()
    monkeypatch.setattr(sys, "stdin", pipe)
    monkeypatch.setattr(cli, "STDIN_WAIT", 0.05)
    try:
        assert cli.read_stdin("hi") == "hi"
    finally:
        pipe.blocked.set()


def test_oversized_stdin_is_refused(monkeypatch, workdir, capsys):
    from eirene import __main__ as cli
    monkeypatch.setattr(cli, "STDIN_LIMIT", 10)
    monkeypatch.setattr(sys, "stdin", _Pipe(b"x" * 100))
    assert cli.read_stdin("hi") is None
    monkeypatch.setattr(sys, "stdin", _Pipe(b"x" * 100))
    assert main(["-p", "hi", "-C", str(workdir)]) == 2
    assert "larger than" in capsys.readouterr().err


def test_slash_commands_ignore_piped_input(monkeypatch):
    from eirene import __main__ as cli
    monkeypatch.setattr(sys, "stdin", _Pipe(b"ignored"))
    assert cli.read_stdin("/providers") == "/providers"


def test_piped_prompt_reaches_the_model(workdir, connected, recording, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Pipe(b"needle-in-stdin"))
    main(["-p", "what is this", "-C", str(workdir), "--tools", "read"])
    assert "needle-in-stdin" in _user_text(recording[0])
