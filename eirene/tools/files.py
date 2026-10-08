"""Sandboxed file operations."""

from __future__ import annotations

import difflib
from pathlib import Path

from ..core.errors import ToolError
from .sandbox import Sandbox

MAX_READ_BYTES = 400_000
MAX_LIST_ENTRIES = 500
BINARY_SNIFF = 8192
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
             ".pytest_cache", "dist", "build", ".tox", "target", ".idea", ".next"}


def read_file(box: Sandbox, path: str, offset: int = 0, limit: int = 0, **kwargs) -> str:
    from . import native
    return native.sync(native.read_file(box, path, offset, limit, **kwargs))


def _decode_fragment(data: bytes, *, final: bool = False) -> tuple[str, int]:
    """Keep continuation byte offsets on UTF-8 boundaries."""
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    text = decoder.decode(data, final=final)
    pending, _ = decoder.getstate()
    return text, len(data) - len(pending)


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
    from . import native
    return native.sync(native.list_dir(box, path, limit=MAX_LIST_ENTRIES))


def glob_files(box: Sandbox, pattern: str, path: str = ".", **kwargs) -> str:
    from . import native
    return native.sync(native.glob_files(box, pattern, path, limit=MAX_LIST_ENTRIES, **kwargs))


def search_text(box: Sandbox, pattern: str, path: str = ".", glob: str = "",
                limit: int = 100, **kwargs) -> str:
    from . import native
    return native.sync(native.search_text(box, pattern, path, glob, limit, **kwargs))


def find_symbol(box: Sandbox, name: str, path: str = ".", limit: int = 100) -> str:
    """Find common language definitions for an exact symbol name."""
    from . import native
    return native.sync(native.find_symbol(box, name, path, limit))


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
