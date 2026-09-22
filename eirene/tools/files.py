"""Sandboxed file operations."""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from ..core.errors import ToolError
from .sandbox import Sandbox

MAX_READ_BYTES = 400_000
MAX_LIST_ENTRIES = 500
BINARY_SNIFF = 8192
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", "dist", "build", ".tox", "target", ".idea", ".next"}


def read_file(box: Sandbox, path: str, offset: int = 0, limit: int = 0) -> str:
    """Read a text file with line numbers."""
    resolved = box.resolve(path)
    if not resolved.exists():
        raise ToolError(f"{box.relative(resolved)} does not exist")
    if resolved.is_dir():
        raise ToolError(f"{box.relative(resolved)} is a directory; use list_dir")
    if _is_binary(resolved):
        size = resolved.stat().st_size
        raise ToolError(f"{box.relative(resolved)} is binary ({size} bytes)")
    try:
        start = max(offset, 0)
        wanted = limit if limit > 0 else 2000
        chunk = []
        used = 0
        more = False
        with resolved.open("r", encoding="utf-8", errors="replace") as handle:
            for index, (line, clipped) in enumerate(_bounded_lines(handle)):
                if index < start:
                    continue
                if len(chunk) >= wanted or used + len(line.encode("utf-8")) > MAX_READ_BYTES:
                    more = True
                    if not chunk:
                        chunk.append(line[:MAX_READ_BYTES])
                    break
                chunk.append(line.rstrip("\r\n"))
                used += len(line.encode("utf-8"))
                if clipped:
                    more = True
                    chunk[-1] += " [line truncated at read limit]"
                    break
    except OSError as exc:
        raise ToolError(f"cannot read {box.relative(resolved)}: {exc}") from exc
    if not chunk:
        return "(empty)" if start == 0 else f"(no lines at offset {start})"
    width = len(str(start + len(chunk)))
    body = "\n".join(f"{start + i + 1:>{width}}\t{line}" for i, line in enumerate(chunk))
    if more:
        body += f"\n… more lines; continue with offset={start + len(chunk)}"
    return body


def _bounded_lines(handle):
    """Never allocate a whole arbitrarily large physical line."""
    while True:
        line = handle.readline(MAX_READ_BYTES)
        if not line:
            return
        clipped = not line.endswith("\n") and len(line) == MAX_READ_BYTES
        if clipped:
            while True:
                rest = handle.readline(MAX_READ_BYTES)
                if not rest or rest.endswith("\n"):
                    break
        yield line, clipped


def write_file(box: Sandbox, path: str, content: str) -> str:
    """Create or overwrite a file."""
    resolved = box.check_write_target(path)
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        existed = resolved.exists()
        resolved.write_text(content, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolError(f"cannot write {box.relative(resolved)}: {exc}") from exc
    verb = "updated" if existed else "created"
    return f"{verb} {box.relative(resolved)} ({len(content.splitlines())} lines)"


def edit_file(box: Sandbox, path: str, old: str, new: str, replace_all: bool = False) -> str:
    """Replace exact text in a file."""
    resolved = box.resolve(path)
    if not resolved.exists():
        raise ToolError(f"{box.relative(resolved)} does not exist")
    if old == new:
        raise ToolError("old_string and new_string are identical")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ToolError(f"cannot read {box.relative(resolved)}: {exc}") from exc
    count = text.count(old)
    if count == 0:
        raise ToolError(f"old_string not found in {box.relative(resolved)}")
    if count > 1 and not replace_all:
        raise ToolError(f"old_string appears {count} times in "
                        f"{box.relative(resolved)}; pass replace_all or add context")
    updated = text.replace(old, new) if replace_all else text.replace(old, new, 1)
    try:
        resolved.write_text(updated, encoding="utf-8", newline="")
    except OSError as exc:
        raise ToolError(f"cannot write {box.relative(resolved)}: {exc}") from exc
    replaced = count if replace_all else 1
    return f"edited {box.relative(resolved)} ({replaced} replacement"\
           f"{'s' if replaced != 1 else ''})"


def list_dir(box: Sandbox, path: str = ".") -> str:
    """List one directory."""
    resolved = box.resolve(path)
    if not resolved.exists():
        raise ToolError(f"{box.relative(resolved)} does not exist")
    if not resolved.is_dir():
        raise ToolError(f"{box.relative(resolved)} is not a directory")
    try:
        entries = sorted(resolved.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        raise ToolError(f"cannot list {box.relative(resolved)}: {exc}") from exc
    if not entries:
        return f"{box.relative(resolved)} is empty"
    rows = []
    for entry in entries[:MAX_LIST_ENTRIES]:
        try:
            if entry.is_dir():
                rows.append(f"{entry.name}/")
            else:
                rows.append(f"{entry.name}  {entry.stat().st_size}b")
        except OSError:
            rows.append(entry.name)
    if len(entries) > MAX_LIST_ENTRIES:
        rows.append(f"… {len(entries) - MAX_LIST_ENTRIES} more")
    return "\n".join(rows)


def glob_files(box: Sandbox, pattern: str, path: str = ".") -> str:
    """Find files matching a glob."""
    root = box.resolve(path)
    if not root.is_dir():
        raise ToolError(f"{box.relative(root)} is not a directory")
    pattern = pattern.strip() or "*"
    if pattern.startswith("/"):
        raise ToolError("pattern must be relative")
    try:
        matches = [p for p in root.glob(pattern) if _keep(p, root)]
    except (OSError, ValueError, NotImplementedError) as exc:
        raise ToolError(f"bad pattern '{pattern}': {exc}") from exc
    matches = [p for p in matches if box.contains(p)]
    if not matches:
        return f"no matches for '{pattern}'"
    matches.sort(key=lambda p: _mtime(p), reverse=True)
    rows = [box.relative(p) for p in matches[:MAX_LIST_ENTRIES]]
    if len(matches) > MAX_LIST_ENTRIES:
        rows.append(f"… {len(matches) - MAX_LIST_ENTRIES} more")
    return "\n".join(rows)


def search_text(box: Sandbox, pattern: str, path: str = ".", glob: str = "",
                limit: int = 100) -> str:
    """Bounded, dependency-free regex search with line locations."""
    root = box.resolve(path)
    try:
        expression = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"bad regular expression: {exc}") from exc
    maximum = max(1, min(int(limit), 500))
    matches = []
    candidates = root.glob(glob or "**/*") if root.is_dir() else [root]
    for candidate in candidates:
        if len(matches) >= maximum:
            break
        if not candidate.is_file() or not _keep(candidate, root if root.is_dir() else root.parent):
            continue
        if not box.contains(candidate) or _is_binary(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                for number, line in enumerate(handle, 1):
                    if expression.search(line):
                        matches.append(f"{box.relative(candidate)}:{number}:{line.rstrip()[:500]}")
                        if len(matches) >= maximum:
                            break
        except OSError:
            continue
    suffix = f"\n… stopped after {maximum} matches" if len(matches) >= maximum else ""
    return "\n".join(matches) + suffix if matches else "no matches"


def find_symbol(box: Sandbox, name: str, path: str = ".", limit: int = 100) -> str:
    """Find common language definitions for an exact symbol name."""
    escaped = re.escape(name.strip())
    if not escaped:
        raise ToolError("symbol name is required")
    pattern = (rf"(?:\b(?:def|class|function|func|fn|struct|enum|interface|type|trait)\s+"
               rf"{escaped}\b|\b{escaped}\s*(?::=|=)\s*(?:function|lambda)|"
               rf"\b{escaped}\s*\([^;]*\)\s*\{{)")
    return search_text(box, pattern, path, "", limit)


def edit_preview(box: Sandbox, path: str, old: str, new: str,
                 replace_all: bool = False) -> str:
    """Unified diff of a pending edit."""
    try:
        resolved = box.resolve(path)
        current = resolved.read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001
        return "\n".join([f"- {line}" for line in old.splitlines()[:40]]
                         + [f"+ {line}" for line in new.splitlines()[:40]])
    if old not in current:
        return "\n".join([f"- {line}" for line in old.splitlines()[:40]]
                         + [f"+ {line}" for line in new.splitlines()[:40]])
    updated = current.replace(old, new) if replace_all else current.replace(old, new, 1)
    return _unified(box.relative(resolved), current, updated)


def diff_preview(box: Sandbox, path: str, content: str) -> str:
    """Unified diff of a pending write."""
    try:
        resolved = box.resolve(path)
    except Exception:
        return content
    old = ""
    if resolved.exists() and resolved.is_file() and not _is_binary(resolved):
        try:
            old = resolved.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            old = ""
    name = box.relative(resolved)
    return _unified(name, old, content)


def _unified(name: str, old: str, content: str) -> str:
    lines = list(difflib.unified_diff(old.splitlines(), content.splitlines(),
                                      fromfile=name, tofile=name, lineterm="", n=2))
    if not lines:
        return "(no change)"
    if len(lines) > 200:
        lines = lines[:200] + [f"… {len(lines) - 200} more diff lines"]
    return "\n".join(lines)


def _keep(path: Path, root: Path) -> bool:
    if not path.is_file():
        return False
    try:
        parts = path.relative_to(root).parts[:-1]
    except ValueError:
        return False
    return not any(part in SKIP_DIRS for part in parts)


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            chunk = handle.read(BINARY_SNIFF)
    except OSError:
        return False
    if b"\0" in chunk:
        return True
    if not chunk:
        return False
    printable = sum(1 for b in chunk if b in (9, 10, 13) or 32 <= b < 127)
    return printable / len(chunk) < 0.7
