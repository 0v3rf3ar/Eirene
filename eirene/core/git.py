"""Git-aware workspace inspection and recoverable checkpoints."""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
import zipfile
import shlex
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .errors import ToolError

MAX_CHECKPOINT_BYTES = 100_000_000
MAX_DIFF_BYTES = 400_000
_POLICY = ContextVar("git_execution_policy", default=None)


@contextmanager
def execution_policy(**policy):
    token = _POLICY.set(policy)
    try:
        yield
    finally:
        _POLICY.reset(token)


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
    tracked = _git(state.root, "ls-files", "-z").stdout.split("\0")
    snapshot_paths = sorted(set(state.paths) | {p for p in tracked if p})
    manifest = {"version": 2, "id": checkpoint_id, "created": time.time(),
                "label": label[:120], "root": str(state.root),
                "branch": state.branch, "head": state.head, "paths": state.paths,
                "files": [], "snapshot_paths": snapshot_paths, "modes": {}, "links": {}}
    total = 0
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            index_path = Path(_git(state.root, "rev-parse", "--git-path", "index").stdout.strip())
            if not index_path.is_absolute():
                index_path = state.root / index_path
            if index_path.is_file():
                bundle.write(index_path, "git-index")
            for relative in snapshot_paths:
                target = _snapshot_target(state.root, relative)
                if target.is_symlink():
                    manifest["links"][relative] = os.readlink(target)
                    continue
                if not target.is_file():
                    continue
                size = target.stat().st_size
                total += size
                if total > MAX_CHECKPOINT_BYTES:
                    raise ToolError("checkpoint exceeds the 100 MB safety limit")
                bundle.write(target, f"files/{relative}")
                manifest["files"].append(relative)
                manifest["modes"][relative] = target.stat().st_mode & 0o777
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
        if manifest.get("version") == 2:
            return _restore_snapshot(root, bundle, manifest, checkpoint_id)
        baseline = set(str(p) for p in manifest.get("paths", []))
        saved = set(str(p) for p in manifest.get("files", []))
        current = set(changed_paths(root))
        # Git restores tracked content/index. Untracked files created since the
        # checkpoint are removed only when Git reports them as changed.
        _git(root, "restore", "--staged", "--worktree", ".", check=False)
        for relative in sorted(current - baseline, reverse=True):
            if _tracked(root, relative):
                continue
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


def _snapshot_target(root: Path, relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ToolError("invalid checkpoint path")
    target = root / path
    parent = target.parent.resolve()
    if parent != root and root not in parent.parents:
        raise ToolError("checkpoint parent escapes repository")
    return target


def _fingerprint(root: Path) -> dict:
    names = set(changed_paths(root)) | set(_git(root, "ls-files", "-z").stdout.split("\0"))
    result = {}
    for name in sorted(names - {""}):
        target = _snapshot_target(root, name)
        if target.is_symlink():
            result[name] = "link:" + os.readlink(target)
        elif target.is_file():
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(65536), b""):
                    digest.update(chunk)
            result[name] = f"{target.stat().st_mode}:{digest.hexdigest()}"
        else:
            result[name] = "missing"
    index = Path(_git(root, "rev-parse", "--git-path", "index").stdout.strip())
    if not index.is_absolute():
        index = root / index
    return {"files": result, "index": hashlib.sha256(index.read_bytes()).hexdigest() if index.exists() else "missing"}


def seal(cwd: Path, checkpoint_id: str) -> None:
    """Remember the end of agent work so later user edits block rollback."""
    root = repository(cwd)
    if isinstance(root, Path):
        target = paths.checkpoints_dir() / f"{_safe_id(checkpoint_id)}.after.json"
        target.write_text(json.dumps(_fingerprint(root)), encoding="utf-8")
        target.chmod(0o600)


def _restore_snapshot(root, bundle, manifest, checkpoint_id):
    head = _git(root, "rev-parse", "--short", "HEAD", check=False).stdout.strip() or "unborn"
    if head != manifest["head"]:
        raise ToolError("HEAD changed since checkpoint; rollback refused")
    seal_path = paths.checkpoints_dir() / f"{checkpoint_id}.after.json"
    if seal_path.exists() and json.loads(seal_path.read_text()) != _fingerprint(root):
        raise ToolError("files changed after the agent finished; rollback would overwrite newer work")
    baseline = set(manifest["snapshot_paths"])
    current = set(changed_paths(root)) | set(_git(root, "ls-files", "-z").stdout.split("\0"))
    # Validate all paths and materialize all archive data before touching the tree.
    names = (baseline | current) - {""}
    targets = {name: _snapshot_target(root, name) for name in names}
    bodies = {name: bundle.read(f"files/{name}") for name in manifest["files"]}
    links = manifest.get("links", {})
    for name, target in targets.items():
        if target.exists() and target.is_dir() and not target.is_symlink():
            raise ToolError(f"checkpoint file became a directory: {name}")
    for name, target in targets.items():
        if target.is_symlink() or (name not in bodies and name not in links and target.is_file()):
            target.unlink()
        if name in bodies:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(bodies[name])
            target.chmod(manifest["modes"].get(name, 0o644))
        elif name in links:
            if target.exists():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(links[name])
    index = Path(_git(root, "rev-parse", "--git-path", "index").stdout.strip())
    if not index.is_absolute():
        index = root / index
    if "git-index" in bundle.namelist():
        index.write_bytes(bundle.read("git-index"))
    elif index.exists():
        index.unlink()
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
    argv = ["git", "-c", "core.fsmonitor=false", *args]
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}
    policy = _POLICY.get()
    if policy and policy.get("backend") != "none":
        from ..tools import isolation
        argv = isolation.command(shlex.join(argv), cwd, **policy)
        env = isolation.environment({"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"})
    try:
        result = subprocess.run(argv, cwd=cwd, text=True,
                                capture_output=True, timeout=30,
                                env=env)
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
