"""Throwaway git copies so a scheduled run cannot touch the real checkout.

Each run gets a self-contained clone rather than a `git worktree`: a worktree's
.git file points back into the real repository, which the command sandbox cannot
reach, so git itself would fail inside the run. Objects are copied, not hardlinked,
because on Windows hardlinks share permissions with the original files.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from ..core import paths
from ..core.errors import SchedulerError
from ..core.subprocesses import external_environment


def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                                timeout=120, stdin=subprocess.DEVNULL,
                                env=external_environment())
    except FileNotFoundError as exc:
        raise SchedulerError("git is needed for an isolated git workspace") from exc
    except subprocess.TimeoutExpired as exc:
        raise SchedulerError("git timed out preparing the isolated copy") from exc
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[:200]
        raise SchedulerError(f"git {args[0]} failed: {detail}")
    return result


def repository_root(cwd: Path) -> Path | None:
    """Top of the git checkout containing cwd, or None."""
    try:
        result = _git(["rev-parse", "--show-toplevel"], cwd, check=False)
    except SchedulerError:
        return None
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip()).resolve()


def create(task_id: str, run_id: str, cwd: Path) -> "Worktree":
    """Clone the last commit into a private copy for one run."""
    root = repository_root(cwd)
    if root is None:
        raise SchedulerError(f"{cwd} is not inside a git repository; an isolated git "
                             "workspace needs one")
    base = _git(["rev-parse", "HEAD"], root).stdout.strip()
    target = paths.task_worktrees_dir() / task_id / run_id
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        _git(["clone", "--quiet", "--no-hardlinks", "--no-checkout", str(root), str(target)],
             target.parent)
        _git(["checkout", "--quiet", "-b", f"eirene/{run_id}", base], target)
        # No way back: the run's commits stay here until someone fetches them.
        _git(["remote", "remove", "origin"], target)
        # A clone does not inherit repository-local settings; keep the same author.
        for key in ("user.name", "user.email"):
            value = _git(["config", key], root, check=False).stdout.strip()
            if value:
                _git(["config", key, value], target)
    except SchedulerError:
        _rmtree(target)
        raise
    relative = Path(cwd).resolve().relative_to(root)
    return Worktree(repo=root, path=target, cwd=target / relative, base=base)


class Worktree:
    """One run's private checkout."""

    def __init__(self, repo: Path, path: Path, cwd: Path, base: str):
        self.repo, self.path, self.cwd, self.base = repo, path, cwd, base

    def changed(self) -> bool:
        """True when the run left edits or commits behind."""
        status = _git(["status", "--porcelain"], self.path, check=False)
        if status.returncode != 0 or status.stdout.strip():
            return True
        head = _git(["rev-parse", "HEAD"], self.path, check=False)
        return head.stdout.strip() != self.base

    def remove(self) -> None:
        _rmtree(self.path)


def kept(task_id: str) -> list[Path]:
    """Copies left behind by runs that changed something, oldest first.

    A copy whose run is still going is not kept yet, and must not be discarded.
    """
    from .history import active_runs
    folder = paths.task_worktrees_dir() / task_id
    try:
        found = sorted(item for item in folder.iterdir() if item.is_dir())
    except OSError:
        return []
    running = active_runs(task_id)
    return [item for item in found if item.name not in running]


def size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(root, name)).st_size
            except OSError:
                continue
    return total


def remove_kept(task_id: str) -> int:
    """Delete every kept copy of a routine; returns how many went."""
    copies = kept(task_id)
    for path in copies:
        _rmtree(path)
    try:
        (paths.task_worktrees_dir() / task_id).rmdir()  # only when nothing is running
    except OSError:
        pass
    return len(copies)


def _rmtree(path: Path) -> None:
    def writable(function, name, _info):
        # Git marks object files read-only, which blocks deletion on Windows.
        os.chmod(name, stat.S_IWRITE)
        function(name)
    if path.exists():
        shutil.rmtree(path, onerror=writable)
