"""Scheduled task locking, history, retries, and environment isolation."""

from __future__ import annotations

import os

from eirene.core import paths
from eirene.headless import run_task
from eirene.scheduling.base import Schedule, Task, load_tasks, save_tasks
from eirene.scheduling.history import last_result, lock_for, record, runs


def task(workdir, **values):
    defaults = dict(id="reliable", name="reliable", prompt="work",
                    cwd=str(workdir), schedule=Schedule("hourly"),
                    provider="chatgpt", model="model")
    defaults.update(values)
    return Task(**defaults)


def test_task_extended_fields_round_trip(workdir):
    original = task(workdir, retries=2, retry_delay=3, timeout=90,
                    allow_overlap=True, timezone="Asia/Tehran", env={"DEMO": "yes"})
    save_tasks([original])
    loaded = load_tasks()[0]
    assert loaded.retries == 2 and loaded.retry_delay == 3
    assert loaded.timeout == 90 and loaded.allow_overlap is True
    assert loaded.timezone == "Asia/Tehran" and loaded.env == {"DEMO": "yes"}


def test_unsafe_environment_keys_are_dropped(workdir):
    body = task(workdir).to_dict()
    body["env"] = {"GOOD_KEY": "yes", "BAD-KEY": "no", "EIRENE_HOME": "/tmp/evil"}
    loaded = Task.from_dict(body)
    assert loaded.env == {"GOOD_KEY": "yes"}


def test_lock_prevents_overlap_and_can_be_reacquired():
    first = lock_for("one")
    second = lock_for("one")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_stale_lock_is_recovered():
    lock = lock_for("stale")
    lock.path.write_text("{}", encoding="utf-8")
    os.utime(lock.path, (1, 1))
    assert lock.acquire(stale_after=1)
    lock.release()


def test_history_is_append_only_and_bounded():
    record("task", "started")
    record("task", "finished", exit_code=0, ok=True, seconds=1.2)
    assert [item["event"] for item in runs("task")] == ["started", "finished"]
    assert last_result("task")["ok"] is True
    assert paths.task_runs_dir().joinpath("task.jsonl").exists()


def test_disabled_task_does_not_run(workdir, capsys):
    save_tasks([task(workdir, enabled=False)])
    assert run_task("reliable") == 0
    assert "disabled" in capsys.readouterr().err


def test_task_retries_and_restores_environment(workdir, monkeypatch):
    from eirene import headless
    calls = []
    def fake_run(*args, **kwargs):
        calls.append(os.environ.get("TASK_VALUE"))
        return 0 if len(calls) == 2 else 1
    monkeypatch.setattr(headless, "run_prompt", fake_run)
    monkeypatch.setattr(headless.time, "sleep", lambda seconds: None)
    save_tasks([task(workdir, retries=2, retry_delay=1, env={"TASK_VALUE": "inside"})])
    os.environ.pop("TASK_VALUE", None)
    assert run_task("reliable") == 0
    assert calls == ["inside", "inside"]
    assert "TASK_VALUE" not in os.environ
    assert last_result("reliable")["attempts"] == 2


def test_lock_left_by_a_dead_process_is_recovered():
    import json as _json
    import subprocess
    import sys
    if os.name == "nt":
        return
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    lock = lock_for("orphan")
    lock.path.parent.mkdir(parents=True, exist_ok=True)
    lock.path.write_text(_json.dumps({"pid": dead.pid, "started": 0}), encoding="utf-8")
    assert lock.acquire(stale_after=10_000)
    lock.release()


def test_lock_outlives_every_retry(workdir, monkeypatch):
    from eirene import headless
    seen = {}
    real_acquire = headless.lock_for("x").__class__.acquire

    def spy(self, stale_after=3900):
        seen["stale_after"] = stale_after
        return real_acquire(self, stale_after)

    monkeypatch.setattr(headless.lock_for("x").__class__, "acquire", spy)
    monkeypatch.setattr(headless, "run_prompt", lambda *a, **k: 0)
    save_tasks([task(workdir, retries=3, timeout=600, retry_delay=60)])
    assert run_task("reliable") == 0
    assert seen["stale_after"] >= 4 * 600 + 3 * 60


def test_task_output_and_access_are_recorded(workdir, monkeypatch):
    from eirene import headless
    from eirene.scheduling.history import finished_runs, load_output
    received = {}

    def fake_run(text, cwd, **kwargs):
        received.update(kwargs, text=text, cwd=cwd)
        kwargs["_result_sink"].update(output="Report: all green.", errors=[],
                                      session="sess1", status="completed")
        return 0

    monkeypatch.setattr(headless, "run_prompt", fake_run)
    save_tasks([task(workdir, access="sandboxed", tools=["read", "web"])])
    assert run_task("reliable") == 0
    assert received["permissions"] == "sandboxed"
    assert received["tool_groups"] == ["read", "web"]
    assert "Allowed tools: read" in received["text"] and "web (" in received["text"]
    item = finished_runs("reliable")[0]
    assert item["summary"] == "Report: all green." and item["session"] == "sess1"
    assert load_output("reliable", item["run"])["output"] == "Report: all green."


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _repo(workdir):
    _git(workdir, "init", "-q")
    _git(workdir, "config", "user.email", "t@example.com")
    _git(workdir, "config", "user.name", "t")
    (workdir / "a.txt").write_text("one\n", encoding="utf-8")
    _git(workdir, "add", ".")
    _git(workdir, "commit", "-qm", "init")


def test_worktree_run_keeps_edits_away_from_the_checkout(workdir, monkeypatch):
    from eirene import headless
    from eirene.scheduling.history import finished_runs
    _repo(workdir)

    def fake_run(text, cwd, **kwargs):
        assert cwd != workdir
        (cwd / "a.txt").write_text("two\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(headless, "run_prompt", fake_run)
    save_tasks([task(workdir, workspace="worktree")])
    assert run_task("reliable") == 0
    assert (workdir / "a.txt").read_text(encoding="utf-8") == "one\n"
    kept = finished_runs("reliable")[0]["worktree"]
    assert kept and (paths.task_worktrees_dir() / "reliable").exists()
    from pathlib import Path
    assert (Path(kept) / "a.txt").read_text(encoding="utf-8") == "two\n"


def test_worktree_without_changes_is_cleaned_up(workdir, monkeypatch):
    from eirene import headless
    from eirene.scheduling.history import finished_runs
    _repo(workdir)
    monkeypatch.setattr(headless, "run_prompt", lambda *a, **k: 0)
    save_tasks([task(workdir, workspace="worktree")])
    assert run_task("reliable") == 0
    assert finished_runs("reliable")[0]["worktree"] == ""
    assert not any((paths.task_worktrees_dir() / "reliable").iterdir())


def test_worktree_needs_a_repository(workdir, monkeypatch):
    from eirene import headless
    from eirene.scheduling.history import finished_runs
    monkeypatch.setattr(headless, "run_prompt", lambda *a, **k: 0)
    save_tasks([task(workdir, workspace="worktree")])
    assert run_task("reliable") == 1
    assert "git repository" in finished_runs("reliable")[0]["errors"][0]


def test_agent_hides_and_blocks_tools_outside_the_granted_groups():
    from eirene.core.agent import Agent
    from eirene.tools import registry

    class Owner:
        def owns(self, name):
            return name.startswith("mcp__")

    fake = type("Fake", (), {})()
    fake.mcp = Owner()
    fake.tool_groups = frozenset({"read", "edit"})
    allowed = lambda name: Agent._tool_allowed(fake, name)
    assert allowed("read_file") and allowed("edit_file") and allowed("ask_user")
    assert not allowed("run_command") and not allowed("web_fetch")
    assert not allowed("delegate_tasks") and not allowed("mcp__server__tool")
    assert registry.group_of("browser_screenshot") == "web"
    fake.tool_groups = None
    assert allowed("run_command")


def _at(text):
    import datetime as dt
    return dt.datetime.strptime(text, "%Y-%m-%d %H:%M").timestamp()


class _Engine:
    def __init__(self, changed=None):
        self.changed = changed

    def password_changed_at(self):
        return self.changed


def _signed_out(workdir, logon="password"):
    from eirene.scheduling.base import Schedule
    return task(workdir, schedule=Schedule("daily", hour=9, minute=0),
                run_signed_out=True, signed_out_logon=logon, created=_at("2026-11-01 12:00"))


def test_routines_flags_a_signed_out_run_that_never_started(workdir, monkeypatch):
    from eirene.commands.routines import _missed
    from eirene.scheduling import history
    item = _signed_out(workdir)
    monkeypatch.setattr(history.time, "time", lambda: _at("2026-11-02 09:00"))
    record(item.id, "started")
    now = _at("2026-11-03 10:00")
    problem = _missed(item, _Engine(), now)
    assert "2026-11-03 09:00 did not start" in problem
    monkeypatch.setattr(history.time, "time", lambda: _at("2026-11-03 09:00"))
    record(item.id, "started")
    assert _missed(item, _Engine(), now) == ""


def test_routines_explains_a_changed_windows_password(workdir, monkeypatch):
    from eirene.commands.routines import _missed
    from eirene.scheduling import history
    item = _signed_out(workdir)
    monkeypatch.setattr(history.time, "time", lambda: _at("2026-11-02 09:00"))
    record(item.id, "started")
    changed = _at("2026-11-02 18:00")
    problem = _missed(item, _Engine(changed), _at("2026-11-03 10:00"))
    assert "password changed on 2026-11-02 18:00" in problem and "create it again" in problem
    # Runs after the change mean the new password is the stored one (or unchanged).
    monkeypatch.setattr(history.time, "time", lambda: _at("2026-11-03 09:00"))
    record(item.id, "started")
    assert _missed(item, _Engine(changed), _at("2026-11-03 10:00")) == ""


def test_routines_does_not_flag_signed_in_or_disabled_routines(workdir):
    from eirene.commands.routines import _missed
    signed_in = task(workdir, created=_at("2026-11-01 12:00"))
    assert _missed(signed_in, _Engine(), _at("2026-11-03 10:00")) == ""
    disabled = _signed_out(workdir)
    disabled.enabled = False
    assert _missed(disabled, _Engine(), _at("2026-11-03 10:00")) == ""


def test_isolated_copy_is_self_contained_and_git_works_inside(workdir):
    import subprocess
    from eirene.scheduling import worktree
    _repo(workdir)
    (workdir / "sub").mkdir()
    (workdir / "sub" / "b.txt").write_text("b\n", encoding="utf-8")
    _git(workdir, "add", "."); _git(workdir, "commit", "-qm", "sub")
    tree = worktree.create("t", "run1", workdir / "sub")
    try:
        assert tree.cwd == tree.path / "sub" and (tree.cwd / "b.txt").exists()
        git_dir = tree.path / ".git"
        assert git_dir.is_dir()  # not a worktree pointer file into the real repository
        assert not (git_dir / "objects" / "info" / "alternates").exists()
        assert subprocess.run(["git", "remote"], cwd=tree.path, capture_output=True,
                              text=True).stdout.strip() == ""
        branch = subprocess.run(["git", "branch", "--show-current"], cwd=tree.path,
                                capture_output=True, text=True).stdout.strip()
        assert branch == "eirene/run1"
        email = subprocess.run(["git", "config", "--local", "user.email"], cwd=tree.path,
                               capture_output=True, text=True).stdout.strip()
        assert email == "t@example.com"  # the source repo's own author carries over
        assert not tree.changed()
        (tree.path / "a.txt").write_text("changed\n", encoding="utf-8")
        _git(tree.path, "commit", "-qam", "run edit")
        assert tree.changed()
        assert (workdir / "a.txt").read_text(encoding="utf-8") == "one\n"
        assert not any(".git/worktrees" in str(p) for p in (workdir / ".git").rglob("*")
                       if "worktrees" in p.parts)
    finally:
        tree.remove()
    assert not tree.path.exists()
