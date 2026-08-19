"""Apply bounded unified patches without invoking a shell."""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.errors import SandboxError, ToolError
from .sandbox import Sandbox

MAX_PATCH_BYTES = 1_000_000
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FilePatch:
    old: str
    new: str
    hunks: list[list[str]]


def apply(box: Sandbox, patch: str) -> str:
    if len(patch.encode("utf-8")) > MAX_PATCH_BYTES:
        raise ToolError("patch exceeds the 1 MB safety limit")
    files = parse(patch)
    if not files:
        raise ToolError("patch contains no file changes")
    prepared = []
    for change in files:
        target_name = _name(change.new if change.new != "/dev/null" else change.old)
        try:
            target = box.check_write_target(target_name)
        except SandboxError as exc:
            raise ToolError(str(exc)) from exc
        original = ""
        if change.old != "/dev/null":
            if not target.exists():
                raise ToolError(f"{target_name} does not exist")
            try:
                original = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise ToolError(f"cannot read {target_name}: {exc}") from exc
        updated = _apply_hunks(original, change.hunks, target_name)
        prepared.append((target, target_name, updated,
                         change.new == "/dev/null"))
    # Validate every hunk before mutating any file.
    originals = []
    for target, name, content, deleting in prepared:
        originals.append((target, target.exists(),
                          target.read_bytes() if target.is_file() else b""))
        try:
            if deleting:
                target.unlink()
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="")
        except OSError as exc:
            for restore, existed, body in reversed(originals):
                try:
                    if existed:
                        restore.parent.mkdir(parents=True, exist_ok=True)
                        restore.write_bytes(body)
                    elif restore.exists():
                        restore.unlink()
                except OSError:
                    pass
            raise ToolError(f"cannot update {name}: {exc}") from exc
    verbs = [f"{'deleted' if deleting else 'patched'} {name}"
             for _, name, _, deleting in prepared]
    return "\n".join(verbs)


def parse(patch: str) -> list[FilePatch]:
    lines = patch.splitlines(keepends=True)
    out = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith("--- "):
            index += 1
            continue
        old = lines[index][4:].strip().split("\t", 1)[0]
        index += 1
        if index >= len(lines) or not lines[index].startswith("+++ "):
            raise ToolError("patch is missing a +++ file header")
        new = lines[index][4:].strip().split("\t", 1)[0]
        index += 1
        hunks = []
        while index < len(lines) and not lines[index].startswith("--- "):
            if lines[index].startswith("@@ "):
                hunk = [lines[index]]
                index += 1
                while index < len(lines) and not lines[index].startswith(("@@ ", "--- ")):
                    if lines[index].startswith((" ", "+", "-", "\\")):
                        hunk.append(lines[index])
                    index += 1
                hunks.append(hunk)
            else:
                index += 1
        if not hunks:
            raise ToolError(f"patch for {_name(new)} has no hunks")
        out.append(FilePatch(old, new, hunks))
    return out


def _apply_hunks(original: str, hunks: list[list[str]], name: str) -> str:
    source = original.splitlines(keepends=True)
    output = []
    cursor = 0
    for hunk in hunks:
        match = HUNK.match(hunk[0].rstrip("\n"))
        if not match:
            raise ToolError(f"invalid hunk header in {name}")
        old_line = int(match.group(1))
        start = max(old_line - 1, 0)
        if start < cursor or start > len(source):
            raise ToolError(f"hunk position is invalid in {name}")
        output.extend(source[cursor:start])
        cursor = start
        for line in hunk[1:]:
            if line.startswith("\\"):
                continue
            marker, body = line[:1], line[1:]
            if marker in (" ", "-"):
                if cursor >= len(source) or source[cursor].rstrip("\r\n") != body.rstrip("\r\n"):
                    raise ToolError(f"patch context does not match {name} near line {cursor + 1}")
                if marker == " ":
                    output.append(source[cursor])
                cursor += 1
            elif marker == "+":
                output.append(body)
    output.extend(source[cursor:])
    return "".join(output)


def _name(raw: str) -> str:
    name = raw.strip()
    if name in ("/dev/null", ""):
        return name
    if name.startswith(("a/", "b/")):
        name = name[2:]
    return name
