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
            if time.time() - self.path.stat().st_mtime > stale_after:
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
