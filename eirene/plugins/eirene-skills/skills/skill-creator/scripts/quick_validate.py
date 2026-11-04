#!/usr/bin/env python3
"""Check a skill folder for the problems that stop it loading or triggering.

  python -m scripts.quick_validate path/to/skill

Checks: SKILL.md exists with front matter; name is lowercase-with-hyphens, at
most 64 characters, and matches the folder; description is present, at most
1024 characters, without angle brackets; only known front-matter keys; files the
body points to exist; no symbolic links. Warns when SKILL.md runs past 500 lines.
Exit status 1 on errors.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from utils import read_skill
else:
    from .utils import read_skill

KNOWN_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools",
              "user-invocable", "disable-model-invocation", "version"}


def validate(folder: Path) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    if not (folder / "SKILL.md").exists():
        return [f"{folder}/SKILL.md is missing"], []
    meta, body, skill_md = read_skill(folder)
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        errors.append("SKILL.md must start with front matter between --- lines")
    name = meta.get("name", "")
    if not name:
        errors.append("front matter has no name")
    elif not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(f"name {name!r} must be lowercase letters, digits and single hyphens, at most 64 characters")
    elif name != folder.name:
        warnings.append(f"name {name!r} differs from the folder name {folder.name!r}")
    description = meta.get("description", "")
    if not description:
        errors.append("front matter has no description; it is what decides when the skill is used")
    else:
        if len(description) > 1024:
            errors.append(f"description is {len(description)} characters; keep it at 1024 or fewer")
        if "<" in description or ">" in description:
            errors.append("description contains < or >, which some loaders reject")
        if len(description) < 40:
            warnings.append("description is very short; say what the skill does and when to use it")
    for key in meta:
        if key not in KNOWN_KEYS:
            warnings.append(f"unknown front-matter key {key!r}")
    lines = body.count("\n")
    if lines > 500:
        warnings.append(f"SKILL.md body is {lines} lines; move detail into references/ and point to it")
    for reference in sorted(set(re.findall(r"`((?:scripts|references|assets|agents|templates|examples)/[^`\s]+)`", body))):
        target = reference.split("#", 1)[0].rstrip(".,:;)")
        if any(ch in target for ch in "*<>{}") or target.endswith("/"):
            continue
        if not (folder / target).exists():
            errors.append(f"SKILL.md mentions {target}, which does not exist")
    for path in folder.rglob("*"):
        if path.is_symlink():
            errors.append(f"{path.relative_to(folder)} is a symbolic link; skills must contain real files")
    return errors, warnings


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip())
        return 2
    folder = Path(sys.argv[1]).resolve()
    errors, warnings = validate(folder)
    for line in errors:
        print(f"error: {line}")
    for line in warnings:
        print(f"warning: {line}")
    print("valid" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
