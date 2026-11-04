"""/review and /security-review: what they collect, refuse, and ask for."""

import os
import subprocess
from types import SimpleNamespace

import pytest

from eirene.commands.review import MAX_EMBEDDED_DIFF, run, security
from eirene.core.modes import Mode


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    (root / "app.py").write_text("x = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "first")
    return root


def fake_app(root):
    said, turns, pushed = [], [], []
    agent = SimpleNamespace(mode=Mode.AUTO)
    app = SimpleNamespace(turn=None, sandbox=SimpleNamespace(root=root), agent=agent, said=said, turns=turns,
                          pushed=pushed, modes=[], refresh_mode_line=lambda: None)
    app.say = lambda text, *a: said.append(text)

    async def push(block):
        pushed.append(block)

    async def run_turn(text, *, record_text=None):
        app.modes.append(agent.mode)
        turns.append((text, record_text))

    app.push, app._run_turn = push, run_turn
    app.spawn = lambda coroutine, **kwargs: __import__("asyncio").ensure_future(coroutine)
    return app


async def finish(app):
    if app.turn:
        await app.turn


@pytest.mark.parametrize("command", [run, security])
async def test_clean_tree_answers_without_using_the_model(repo, command):
    app = fake_app(repo)
    await command(app, "")
    assert not app.turns and "nothing to review" in app.said[0]


async def test_missing_base_is_caught_before_using_the_model(repo):
    app = fake_app(repo)
    await run(app, "no-such-branch")
    assert not app.turns and app.said == ["no such Git revision: no-such-branch"]


@pytest.mark.parametrize("base", ["--output=x", "main;rm", "$(x)", "a b"])
async def test_unsafe_base_is_refused(repo, base):
    app = fake_app(repo)
    await run(app, base)
    assert not app.turns and app.said == ["invalid Git base revision"]


async def test_review_includes_staged_unstaged_and_untracked_read_only(repo):
    (repo / "app.py").write_text("x = 2\n")
    (repo / "staged.py").write_text("y = 1\n")
    git(repo, "add", "staged.py")
    (repo / "new.py").write_text("z = 1\n")
    app = fake_app(repo)
    await run(app, "")
    await finish(app)
    text, record = app.turns[0]
    assert "+x = 2" in text and "+y = 1" in text and "new.py" in text and "not in the diff" in text
    assert "strict read-only code review" in text and "No findings" in text
    assert record == "Review changes in staged, unstaged and untracked changes"
    assert app.modes == [Mode.PLAN] and app.agent.mode is Mode.AUTO


async def test_base_compares_from_where_the_branch_split(repo):
    git(repo, "checkout", "-qb", "feature")
    (repo / "feature.py").write_text("mine = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "mine")
    git(repo, "checkout", "-q", "main")
    (repo / "theirs.py").write_text("theirs = 1\n")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "theirs")
    git(repo, "checkout", "-q", "feature")
    app = fake_app(repo)
    await run(app, "main")
    await finish(app)
    assert "mine = 1" in app.turns[0][0] and "theirs = 1" not in app.turns[0][0]


async def test_large_diff_is_read_file_by_file(repo):
    (repo / "app.py").write_text("x = 1\n" + "line\n" * MAX_EMBEDDED_DIFF)
    app = fake_app(repo)
    await run(app, "")
    await finish(app)
    text = app.turns[0][0]
    assert "too large to include" in text and "-- <path>" in text and "app.py" in text
    assert len(text) < MAX_EMBEDDED_DIFF


@pytest.mark.skipif(os.name == "nt", reason="uses a shell script")
async def test_repository_config_cannot_run_a_program(repo, tmp_path):
    marker = tmp_path / "ran"
    tool = tmp_path / "tool.sh"
    tool.write_text(f"#!/bin/sh\ntouch {marker}\n")
    tool.chmod(0o755)
    git(repo, "config", "diff.external", str(tool))
    git(repo, "config", "core.fsmonitor", str(tool))
    (repo / "app.py").write_text("x = 2\n")
    app = fake_app(repo)
    await security(app, "")
    await finish(app)
    assert not marker.exists()
    assert "+x = 2" in app.turns[0][0]


async def test_security_review_requires_an_attack_and_guards_against_the_code_under_review(repo):
    (repo / "app.py").write_text("x = 2\n")
    app = fake_app(repo)
    await security(app, "")
    await finish(app)
    text, record = app.turns[0]
    assert record.startswith("Security review of changes")
    for needed in ("strict read-only security review", "Attack:", "Category:", "untrusted input", "Never quote a secret",
                   "instructions to you", "does not prove the code is secure"):
        assert needed in text
    assert app.modes == [Mode.PLAN]


async def test_review_refuses_during_a_turn_and_outside_git(tmp_path):
    app = fake_app(tmp_path)
    await security(app, "")
    assert "requires a Git repository" in app.said[0]
    busy = fake_app(tmp_path)
    busy.turn = SimpleNamespace(done=lambda: False)
    await security(busy, "")
    assert "finish or stop" in busy.said[0]


def test_git_commands_given_to_the_model_stay_allowed_in_plan_mode():
    from eirene.tools.shell import is_safe
    assert is_safe("git diff --no-ext-diff --no-textconv")
    assert is_safe("git diff --no-ext-diff --no-textconv --cached -- app.py")
    assert is_safe("git status --short")


async def test_a_review_turn_can_really_use_its_tools_and_cannot_write(repo):
    from eirene.core.agent import Agent, ToolFinished
    from eirene.core.config import Config
    from eirene.core.session import Session
    from eirene.providers.base import Done, TextDelta, ToolCall
    from eirene.tools.sandbox import Sandbox

    (repo / "app.py").write_text("x = 2\n")
    steps = [ToolCall("a", "run_command", {"command": "git diff --no-ext-diff --no-textconv -- app.py"}),
             ToolCall("b", "read_file", {"path": "app.py"}),
             ToolCall("c", "search_text", {"pattern": "x"}),
             ToolCall("d", "write_file", {"path": "app.py", "content": "hacked\n"})]

    class Provider:
        supports_tools = True
        protocol = "test"

        def __init__(self):
            self.turn = 0

        async def stream(self, messages, model, **kwargs):
            if self.turn < len(steps):
                yield steps[self.turn]
                self.turn += 1
                yield Done("tool_use")
                return
            yield TextDelta("No findings")
            yield Done("stop")

        async def close(self):
            pass

    agent = Agent(Session.create(repo), Config.load(), Sandbox(repo))
    agent.mode = Mode.PLAN
    agent.use(Provider(), "test", "m")
    results = {}
    async for event in agent.run("review"):
        if isinstance(event, ToolFinished):
            results[event.call_id if hasattr(event, "call_id") else event.id] = (event.is_error, str(event.result))
    await agent.close()
    assert not results["a"][0] and "+x = 2" in results["a"][1]
    assert not results["b"][0] and not results["c"][0]
    assert results["d"][0]
    assert (repo / "app.py").read_text() == "x = 2\n"
