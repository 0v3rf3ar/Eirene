"""Sandboxed file operations."""

from __future__ import annotations

import difflib
import errno
import os
import stat
import tempfile
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


def _edit_text(text: str, old: str, new: str, replace_all: bool, name: str) -> tuple[str, int]:
    if not isinstance(old, str) or not isinstance(new, str):
        raise ToolError("old_string and new_string must be strings")
    if not isinstance(replace_all, bool):
        raise ToolError("replace_all must be a boolean")
    if not old:
        raise ToolError("old_string must not be empty; use write_file for a complete file")
    old, new = _edit_newlines(text, old, new)
    if old == new:
        raise ToolError("old_string and new_string are identical")
    count = text.count(old)
    if not count:
        raise ToolError(f"no match in {name}; reread the target and copy exact text without line numbers")
    if count > 1 and not replace_all:
        raise ToolError(f"{count} matches in {name}; add unique context or set replace_all=true")
    return text.replace(old, new, -1 if replace_all else 1), count if replace_all else 1


def _edit_error(name: str, exc: OSError) -> ToolError:
    reasons = {
        errno.ENOSPC: "disk full; free space and retry",
        errno.EDQUOT: "disk quota exceeded; free space or increase quota",
        errno.EACCES: "permission denied; check file and parent directory permissions",
        errno.EPERM: "operation denied; check permissions or file protection",
        errno.EROFS: "read-only filesystem; use a writable location",
        errno.ENOENT: "file or parent missing; reread the target path",
        errno.ENOTDIR: "a path component is not a directory",
        errno.EISDIR: "target is a directory; select a text file",
        errno.EIO: "filesystem I/O error; check storage before retrying",
        errno.EMFILE: "too many open files; close handles and retry",
        errno.ENFILE: "system file-handle limit reached; retry later",
    }
    return ToolError(f"cannot edit {name}: {reasons.get(exc.errno, exc.strerror or str(exc))}; edit not committed")


def _snapshot(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
            info.st_ctime_ns, info.st_mode, info.st_uid, info.st_gid, info.st_nlink)


def edit_file(box: Sandbox, path: str, old: str, new: str, replace_all: bool = False) -> str:
    """Validate exact replacements and commit using a sibling atomic replacement."""
    resolved = box.check_write_target(path)
    name = box.relative(resolved)
    temporary = None
    try:
        if not stat.S_ISREG(resolved.stat().st_mode):
            raise ToolError(f"cannot edit {name}: target must be a regular text file")
        # Opening for update checks file write permission without truncating it.
        with resolved.open("r+b") as source:
            before = os.fstat(source.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ToolError(f"cannot edit {name}: target must be a regular text file")
            if before.st_nlink > 1:
                raise ToolError(f"cannot edit {name}: hard-linked file; atomic replacement would break links")
            original = source.read()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ToolError(f"cannot edit {name}: invalid UTF-8; use a tool for its encoding") from exc
        if b"\0" in original:
            raise ToolError(f"cannot edit {name}: binary file; select a text file")
        updated, replaced = _edit_text(text, old, new, replace_all, name)
        try:
            encoded = updated.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ToolError(f"cannot edit {name}: replacement contains invalid Unicode") from exc
        with tempfile.NamedTemporaryFile(mode="wb", dir=resolved.parent,
                                         prefix=".eirene-edit-", delete=False) as target:
            temporary = Path(target.name)
            target.write(encoded)
            target.flush()
            # Preserve ownership before mode (chown can reset mode bits).
            created = os.fstat(target.fileno())
            if (created.st_uid, created.st_gid) != (before.st_uid, before.st_gid):
                os.chown(temporary, before.st_uid, before.st_gid)
            if hasattr(os, "listxattr"):
                for key in os.listxattr(resolved):
                    os.setxattr(temporary, key, os.getxattr(resolved, key))
            os.chmod(temporary, stat.S_IMODE(before.st_mode))
            os.fsync(target.fileno())
        if _snapshot(resolved.stat()) != _snapshot(before) or resolved.read_bytes() != original:
            raise ToolError(f"cannot edit {name}: file changed during edit; reread and retry")
        os.replace(temporary, resolved)
        temporary = None
    except OSError as exc:
        raise _edit_error(name, exc) from exc
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError as cleanup:
                # Report residue as well as the original error, without its contents.
                prior = cleanup.__context__
                raise ToolError(f"{prior or 'edit failed'}; temporary cleanup failed: "
                                f"{temporary.name}: {cleanup.strerror}") from cleanup
    return f"edited {name} ({replaced} replacement{'s' if replaced != 1 else ''})"


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


def _edit_newlines(text: str, old: str, new: str) -> tuple[str, str]:
    # Readers display normalized newlines; preserve CRLF when applying their text.
    if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
        old = old.replace("\r\n", "\n").replace("\n", "\r\n")
        new = new.replace("\r\n", "\n").replace("\n", "\r\n")
    return old, new


def edit_preview(box: Sandbox, path: str, old: str, new: str,
                 replace_all: bool = False) -> str:
    """Unified diff of a pending edit."""
    resolved = box.resolve(path)
    name = box.relative(resolved)
    try:
        current = resolved.read_bytes().decode("utf-8")
    except OSError as exc:
        return str(_edit_error(name, exc))
    except UnicodeDecodeError:
        return f"cannot edit {name}: invalid UTF-8"
    try:
        updated, _ = _edit_text(current, old, new, replace_all, name)
    except ToolError as exc:
        return str(exc)
    return _unified(name, current, updated)



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
