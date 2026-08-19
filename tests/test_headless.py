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
