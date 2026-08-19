"""Git-aware workspace inspection and recoverable checkpoints."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .errors import ToolError

MAX_CHECKPOINT_BYTES = 100_000_000
MAX_DIFF_BYTES = 400_000


@dataclass
class RepoState:
    root: Path
    branch: str
    head: str
    paths: list[str]


def repository(cwd: Path) -> Path | None:
    result = _git(cwd, "rev-parse", "--show-toplevel", check=False)
    if result.returncode:
        return None
    try:
        root = Path(result.stdout.strip()).resolve()
    except OSError:
        return None
    return root if root == cwd.resolve() or root in cwd.resolve().parents else None


def inspect(cwd: Path) -> RepoState | None:
    root = repository(cwd)
    if root is None:
        return None
    branch = _git(root, "branch", "--show-current", check=False).stdout.strip()
    head = _git(root, "rev-parse", "--short", "HEAD", check=False).stdout.strip()
    return RepoState(root, branch or "detached/unborn", head or "unborn",
                     changed_paths(root))


def changed_paths(root: Path) -> list[str]:
    raw = _git(root, "status", "--porcelain=v1", "-z",
               "--untracked-files=all").stdout
    found: list[str] = []
    entries = raw.split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry:
            continue
        name = entry[3:] if len(entry) >= 4 else entry
        # Rename/copy records have a second NUL-delimited path. Preserve both
        # sides so rollback can reconstruct the pre-action tree.
        if entry[:2].strip() in {"R", "C"} and index < len(entries):
            old = entries[index]
            index += 1
            if old:
                found.append(old)
        if name:
            found.append(name)
    return sorted(set(found))


def status(cwd: Path) -> str:
    state = inspect(cwd)
    if state is None:
        return "not a Git repository"
    body = _git(state.root, "status", "--short", "--branch").stdout.rstrip()
    return body or f"## {state.branch} ({state.head})\nworking tree clean"


def diff(cwd: Path, path: str = "") -> str:
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    args = ["diff", "--no-ext-diff", "--binary", "--"]
    if path:
        args.append(path)
    unstaged = _git(root, *args).stdout
    cached_args = ["diff", "--cached", "--no-ext-diff", "--binary", "--"]
    if path:
        cached_args.append(path)
    staged = _git(root, *cached_args, check=False).stdout
    text = ""
    if staged:
        text += "# staged\n" + staged
    if unstaged:
        text += ("\n" if text else "") + "# unstaged\n" + unstaged
    if not text:
        untracked = [p for p in changed_paths(root) if not _tracked(root, p)]
        if path:
            untracked = [p for p in untracked if p == path or p.startswith(path + "/")]
        if untracked:
            text = "# untracked\n" + "\n".join(untracked)
    if len(text.encode("utf-8")) > MAX_DIFF_BYTES:
        text = text.encode("utf-8")[:MAX_DIFF_BYTES].decode("utf-8", "replace") \
            + "\n… diff truncated"
    return text.rstrip() or "working tree clean"


def diff_against(cwd: Path, base: str) -> str:
    """Diff the working tree and HEAD against a validated base revision."""
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    revision = str(base or "").strip()
    if not revision or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@{}^-]*", revision):
        raise ToolError("invalid base revision")
    verified = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}", check=False)
    if verified.returncode:
        raise ToolError(f"unknown base revision '{revision}'")
    result = _git(root, "diff", "--no-ext-diff", "--binary", revision, "--",
                  check=False)
    if result.returncode:
        raise ToolError(result.stderr.strip() or "git diff failed")
    raw = result.stdout.encode("utf-8")
    if len(raw) > MAX_DIFF_BYTES:
        return raw[:MAX_DIFF_BYTES].decode("utf-8", "replace") + "\n… diff truncated"
    return result.stdout.rstrip() or f"no changes against {revision}"


def checkpoint(cwd: Path, label: str = "") -> str:
    """Snapshot every currently changed path without touching the Git index."""
    state = inspect(cwd)
    if state is None:
        raise ToolError("not a Git repository")
    checkpoint_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    archive = paths.checkpoints_dir() / f"{checkpoint_id}.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    manifest = {"version": 1, "id": checkpoint_id, "created": time.time(),
                "label": label[:120], "root": str(state.root),
                "branch": state.branch, "head": state.head, "paths": state.paths,
                "files": []}
    total = 0
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for relative in state.paths:
                target = _inside(state.root, relative)
                if not target.is_file() or target.is_symlink():
                    continue
                size = target.stat().st_size
                total += size
                if total > MAX_CHECKPOINT_BYTES:
                    raise ToolError("checkpoint exceeds the 100 MB safety limit")
                bundle.write(target, f"files/{relative}")
                manifest["files"].append(relative)
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        if os.name != "nt":
            archive.chmod(0o600)
    except Exception:
        try:
            archive.unlink()
        except OSError:
            pass
        raise
    return checkpoint_id


def rollback(cwd: Path, checkpoint_id: str) -> str:
    """Restore exactly the dirty tree captured by a checkpoint."""
    archive = paths.checkpoints_dir() / f"{_safe_id(checkpoint_id)}.zip"
    if not archive.is_file():
        raise ToolError(f"no checkpoint '{checkpoint_id}'")
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        if Path(manifest.get("root", "")).resolve() != root:
            raise ToolError("checkpoint belongs to a different repository")
        baseline = set(str(p) for p in manifest.get("paths", []))
        saved = set(str(p) for p in manifest.get("files", []))
        current = set(changed_paths(root))
        # Git restores tracked content/index. Untracked files created since the
        # checkpoint are removed only when Git reports them as changed.
        _git(root, "restore", "--staged", "--worktree", ".", check=False)
        for relative in sorted(current - baseline, reverse=True):
            target = _inside(root, relative)
            if target.is_file() or target.is_symlink():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
        for relative in baseline:
            target = _inside(root, relative)
            if relative in saved:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.open(f"files/{relative}") as source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
            elif target.exists() or target.is_symlink():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
    return f"restored checkpoint {checkpoint_id} ({len(baseline)} paths)"


def commit(cwd: Path, message: str, selected: list[str]) -> str:
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    message = " ".join(message.split())
    if not message:
        raise ToolError("commit message is required")
    if not selected:
        raise ToolError("name at least one path to commit")
    clean = []
    for relative in selected:
        target = _inside(root, relative)
        clean.append(str(target.relative_to(root)))
    _git(root, "add", "--", *clean)
    result = _git(root, "-c", "commit.gpgsign=false", "commit", "-m", message,
                  "--", *clean, check=False)
    if result.returncode:
        raise ToolError((result.stderr or result.stdout).strip() or "git commit failed")
    return result.stdout.strip()


def list_checkpoints(cwd: Path) -> str:
    root = repository(cwd)
    rows = []
    for archive in sorted(paths.checkpoints_dir().glob("*.zip"), reverse=True):
        try:
            with zipfile.ZipFile(archive) as bundle:
                data = json.loads(bundle.read("manifest.json"))
            if root and Path(data.get("root", "")).resolve() != root:
                continue
            rows.append(f"{data['id']}  {data.get('label') or 'checkpoint'}  "
                        f"{len(data.get('paths', []))} paths")
        except (OSError, KeyError, ValueError, zipfile.BadZipFile):
            continue
    return "\n".join(rows) or "no checkpoints"


def create_worktree(cwd: Path, path: str, branch: str = "") -> str:
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    target = _inside(root, path)
    if target.exists():
        raise ToolError(f"worktree path already exists: {path}")
    args = ["worktree", "add"]
    if branch:
        if not _valid_branch(branch):
            raise ToolError("invalid branch name")
        args.extend(["-b", branch])
    args.append(str(target))
    result = _git(root, *args)
    detail = result.stdout.strip()
    return f"created worktree {path}" + (f" ({detail})" if detail else "")


def remove_worktree(cwd: Path, path: str) -> str:
    root = repository(cwd)
    if root is None:
        raise ToolError("not a Git repository")
    target = _inside(root, path)
    registered = _git(root, "worktree", "list", "--porcelain").stdout.splitlines()
    if f"worktree {target}" not in registered:
        raise ToolError(f"not a registered Git worktree: {path}")
    result = _git(root, "worktree", "remove", str(target))
    return result.stdout.strip() or f"removed worktree {path}"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(["git", *args], cwd=cwd, text=True,
                                capture_output=True, timeout=30,
                                env={**os.environ, "GIT_TERMINAL_PROMPT": "0",
                                     "GIT_PAGER": "cat"})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ToolError(f"cannot run Git: {exc}") from exc
    if check and result.returncode:
        raise ToolError((result.stderr or result.stdout).strip() or "Git failed")
    return result


def _inside(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise ToolError(f"Git path escapes repository: {relative}")
    return target


def _tracked(root: Path, relative: str) -> bool:
    return _git(root, "ls-files", "--error-unmatch", "--", relative,
                check=False).returncode == 0


def _safe_id(value: str) -> str:
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in value):
        raise ToolError("invalid checkpoint id")
    return value


def _valid_branch(value: str) -> bool:
    if not value or value.startswith(("-", ".")) or value.endswith((".", "/")):
        return False
    return (all(char.isalnum() or char in "-_/.'" for char in value)
            and ".." not in value)
