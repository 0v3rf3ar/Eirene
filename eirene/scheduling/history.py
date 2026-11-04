"""Scheduled run locks and append-only execution history."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core import paths
from ..core.errors import SchedulerError


@dataclass
class TaskLock:
    task_id: str
    path: Path
    acquired: bool = False

    def acquire(self, stale_after: int = 3900) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            if (time.time() - self.path.stat().st_mtime > stale_after
                    or _owner_gone(self.path)):
                self.path.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            return False
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"pid": os.getpid(), "started": time.time()}, handle)
            self.acquired = True
            return True
        except FileExistsError:
            return False
        except OSError as exc:
            raise SchedulerError(f"cannot create task lock: {exc}") from exc

    def release(self) -> None:
        if self.acquired:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.acquired = False


def _owner_gone(path: Path) -> bool:
    """True when the lock names a process that no longer exists (POSIX only)."""
    if os.name == "nt":
        # os.kill on Windows terminates rather than probes.
        return False
    try:
        pid = int(json.loads(path.read_text(encoding="utf-8")).get("pid", 0))
    except (OSError, ValueError, TypeError, AttributeError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def lock_for(task_id: str) -> TaskLock:
    return TaskLock(task_id, paths.task_locks_dir() / f"{task_id}.lock")


def record(task_id: str, event: str, **fields: Any) -> None:
    path = paths.task_runs_dir() / f"{task_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": time.time(), "event": event, **fields},
                                    ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            path.chmod(0o600)
    except OSError as exc:
        raise SchedulerError(f"cannot record task history: {exc}") from exc


def runs(task_id: str, limit: int = 20) -> list[dict[str, Any]]:
    path = paths.task_runs_dir() / f"{task_id}.jsonl"
    found = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        found.append(item)
                except (json.JSONDecodeError, ValueError):
                    continue
    except OSError:
        return []
    return found[-max(1, min(limit, 100)):]


def last_result(task_id: str) -> dict[str, Any] | None:
    return next((item for item in reversed(runs(task_id, 100))
                 if item.get("event") == "finished"), None)


KEEP_OUTPUTS = 50
OUTPUT_LIMIT = 200_000


def save_output(task_id: str, run_id: str, result: dict[str, Any]) -> None:
    """Keep one run's answer and details; older runs beyond KEEP_OUTPUTS are pruned."""
    folder = paths.task_outputs_dir() / task_id
    folder.mkdir(parents=True, exist_ok=True)
    body = dict(result)
    text = str(body.get("output") or "")
    if len(text) > OUTPUT_LIMIT:
        body["output"] = text[:OUTPUT_LIMIT] + "\n… output truncated"
    path = folder / f"{run_id}.json"
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        if os.name != "nt":
            path.chmod(0o600)
        for old in sorted(folder.glob("*.json"))[:-KEEP_OUTPUTS]:
            old.unlink(missing_ok=True)
    except OSError as exc:
        raise SchedulerError(f"cannot save task output: {exc}") from exc


def load_output(task_id: str, run_id: str) -> dict[str, Any] | None:
    if not run_id or "/" in run_id or "\\" in run_id or ".." in run_id:
        return None
    try:
        body = json.loads((paths.task_outputs_dir() / task_id / f"{run_id}.json")
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return body if isinstance(body, dict) else None


def finished_runs(task_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Completed or skipped invocations, newest first."""
    done = [item for item in runs(task_id, 100)
            if item.get("event") in ("finished", "skipped")]
    return list(reversed(done))[:limit]


def remove_history(task_id: str) -> None:
    """Forget a removed task's events, outputs and kept git copies."""
    import shutil
    from . import worktree
    (paths.task_runs_dir() / f"{task_id}.jsonl").unlink(missing_ok=True)
    shutil.rmtree(paths.task_outputs_dir() / task_id, ignore_errors=True)
    try:
        worktree.remove_kept(task_id)
    except OSError:
        pass


def active_runs(task_id: str) -> set[str]:
    """Run ids that started and have not finished while the routine's lock is held."""
    if not lock_for(task_id).path.exists():
        return set()
    started: set[str] = set()
    for item in runs(task_id, 100):
        run = str(item.get("run") or "")
        if item.get("event") == "started" and run:
            started.add(run)
        elif item.get("event") == "finished":
            started.discard(run)
    return started


def last_start(task_id: str) -> float | None:
    """When Eirene last began handling an invocation (started or skipped)."""
    for item in reversed(runs(task_id, 100)):
        if item.get("event") in ("started", "skipped"):
            try:
                return float(item.get("ts"))
            except (TypeError, ValueError):
                return None
    return None
