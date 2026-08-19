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
