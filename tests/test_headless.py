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
    assert main(["-p", "hi", "-C", str(workdir)]) == 1
    assert "/connect" in capsys.readouterr().err


def test_prompt_run_reports_a_bad_key(workdir, connected, capsys):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "nope"}},
                              headers={"content-type": "application/json"})
    base.set_transport(httpx.MockTransport(handler))
    try:
        assert main(["-p", "hi", "-C", str(workdir)]) == 1
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
    assert main(["-p", "hi", "-C", str(workdir), "--json"]) == 1
    result = json.loads(capsys.readouterr().out)
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
