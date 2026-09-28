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


def read_file(box: Sandbox, path: str, offset: int = 0, limit: int = 0, *,
              max_chars: int = 24000, tail: bool = False, pattern: str = "",
              context: int = 2, byte_offset: int | None = None) -> str:
    """Size-aware head/tail or grep-style text reads, bounded before rendering."""
    from collections import deque
    from ..core.text import safe_text

    resolved = box.resolve(path)
    try:
        if not resolved.exists():
            raise ToolError(f"{box.relative(resolved)} does not exist")
        if not resolved.is_file():
            raise ToolError(f"{box.relative(resolved)} is not a regular file; use list_dir")
        size = resolved.stat().st_size
        if _is_binary(resolved):
            raise ToolError(f"{box.relative(resolved)} is binary ({size} bytes); use read_image or a bounded hex dump")
        maximum = max(0, min(int(max_chars), MAX_READ_BYTES))
        if maximum < 256:
            return "File read deferred: insufficient context; compact history or request a smaller response."[:maximum]
        # Equivalent to wc -lc, without shell interpolation or unbounded memory.
        total = 0
        last = b""
        with resolved.open("rb") as handle:
            while data := handle.read(65536):
                total += data.count(b"\n")
                last = data[-1:]
        total += bool(size and last != b"\n")
        header = f"File: {box.relative(resolved)} ({size} bytes, {total} lines)\n"
        footer_room = 220
        room = max(0, maximum - len(header) - footer_room)
        if byte_offset is not None:
            with resolved.open("rb") as handle:
                handle.seek(max(0, byte_offset))
                data = handle.read(max(1, room // 4))
                next_byte = handle.tell()
            text, consumed = _decode_fragment(data, final=next_byte >= size)
            next_byte -= len(data) - consumed
            text = safe_text(text)
            note = f"\nContinue with byte_offset={next_byte}; byte ranges may split UTF-8 characters." if next_byte < size else "\n(end of file)"
            return (header + text + note)[:maximum]
        try:
            expression = re.compile(pattern) if pattern else None
        except re.error as exc:
            raise ToolError(f"bad regular expression: {exc}") from exc
        start = max(0, offset)
        wanted = max(1, limit) if limit > 0 else (20 if tail else total)
        if tail:
            start = max(start, total - wanted)
        before = deque(maxlen=max(0, min(context, 20)))
        rows = []
        used = 0
        through = 0
        next_line = start
        next_byte = None
        more = False
        with resolved.open("rb") as handle:
            number = 0
            while handle.tell() < size:
                position = handle.tell()
                raw = handle.readline(MAX_READ_BYTES)
                number += 1
                partial = not raw.endswith(b"\n") and handle.tell() < size
                line = safe_text(raw.decode("utf-8", "replace").rstrip("\r\n"))
                row = f"{number}\t{line}"
                if partial:
                    # Drain this physical line with bounded allocations.
                    ending = raw[-max(1, room // 4):]
                    while rest := handle.readline(MAX_READ_BYTES):
                        ending = (ending + rest)[-max(1, room // 4):]
                        if rest.endswith(b"\n"):
                            break
                    if tail:
                        row = f"{number}\t… " + safe_text(ending.decode("utf-8", "replace").rstrip("\r\n"))
                if number <= start:
                    continue
                matched = expression is None or expression.search(line) is not None
                if matched and expression:
                    through = number + max(0, min(context, 20))
                    pending = list(before) + [(number, row, position, raw)]
                    before.clear()
                elif matched or number <= through:
                    pending = [(number, row, position, raw)]
                else:
                    before.append((number, row, position, raw))
                    continue
                if tail:
                    # Like tail piped into a byte bound: retain the ending even
                    # when the requested number of lines exceeds the budget.
                    if len(row) + 1 > room:
                        row = f"{number}\t… " + row[-max(0, room - len(str(number)) - 6):]
                    rows.append((number, row))
                    used += len(row) + 1
                    while rows and (used > room or len(rows) > wanted):
                        used -= len(rows.pop(0)[1]) + 1
                    continue
                for n, value, pos, source in pending:
                    if rows and n <= rows[-1][0]:
                        continue
                    if len(rows) >= wanted or used + len(value) + 1 > room:
                        more = True
                        next_line = n - 1
                        if not rows:
                            # A long line is paged by bytes rather than silently lost.
                            fragment = source[:max(1, room // 4)]
                            text, consumed = _decode_fragment(fragment)
                            rows.append((n, f"{n}\t" + safe_text(text)))
                            next_byte = pos + consumed
                        break
                    rows.append((n, value))
                    used += len(value) + 1
                    next_line = n
                    if partial:
                        more = True
                        next_byte = position + len(raw)
                if more:
                    break
        body = "\n".join(row for _, row in rows) or ("no matches" if expression else "(empty)")
        if more:
            resume = f"byte_offset={next_byte}" if next_byte is not None else f"offset={next_line}"
            note = f"\n… more lines; continue with {resume}. Use pattern with context, tail=true, or a smaller line range for focused evidence."
        elif tail:
            first = rows[0][0] if rows else total + 1
            note = f"\n(end of file; earlier lines omitted, inspect offset/limit or pattern/context before line {first})" if first > 1 else "\n(end of file)"
        else:
            note = "\n(end of selected range)" if start or expression else "\n(end of file)"
        return (header + body + note)[:maximum]
    except OSError as exc:
        raise ToolError(f"cannot read {box.relative(resolved)}: {exc}") from exc


def _decode_fragment(data: bytes, *, final: bool = False) -> tuple[str, int]:
    """Keep continuation byte offsets on UTF-8 boundaries."""
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data, final=final)
    pending, _ = decoder.getstate()
    return text, len(data) - len(pending)


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
    text = chunk.decode("utf-8", "replace")
    printable = sum(1 for char in text if char.isprintable() or char in "\t\n\r")
    return printable / len(text) < 0.7 or text.count("\ufffd") / len(text) > 0.1
