#!/usr/bin/env python3
"""Package a skill as a .skill file (a zip), or install it into Eirene.

  python -m scripts.package_skill path/to/skill [output_dir]
  python -m scripts.package_skill path/to/skill --install [--replace]

The skill is validated first. Packaging leaves out workspaces, caches, version
control and node_modules. --install copies the folder into Eirene's skills
directory ($EIRENE_HOME/skills, default ~/.local/share/eirene/skills), where
/skills can enable it; an existing skill of the same name is kept unless
--replace is given.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from quick_validate import validate
else:
    from .quick_validate import validate

SKIP_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "evals"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}


def included(folder: Path):
    for path in sorted(folder.rglob("*")):
        relative = path.relative_to(folder)
        if any(part in SKIP_DIRS or part.endswith("-workspace") for part in relative.parts):
            continue
        if path.is_file() and path.name not in SKIP_FILES and not path.name.endswith(".pyc"):
            yield path, relative


def main() -> int:
    parser = argparse.ArgumentParser(description="Package or install a skill.")
    parser.add_argument("skill", type=Path)
    parser.add_argument("output", nargs="?", type=Path, help="folder for the .skill file (default: current)")
    parser.add_argument("--install", action="store_true", help="copy into Eirene's skills directory")
    parser.add_argument("--replace", action="store_true", help="with --install, replace an existing copy")
    args = parser.parse_args()
    folder = args.skill.resolve()
    errors, warnings = validate(folder)
    for line in warnings:
        print(f"warning: {line}")
    if errors:
        for line in errors:
            print(f"error: {line}")
        print("fix the errors above first")
        return 1
    name = folder.name
    if args.install:
        home = Path(os.environ.get("EIRENE_HOME") or Path.home() / ".local" / "share" / "eirene").expanduser()
        target = home / "skills" / name
        if target.exists():
            if not args.replace:
                print(f"{target} already exists; pass --replace to overwrite it")
                return 1
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for path, relative in included(folder):
            (target / relative).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target / relative)
        print(f"installed {name} → {target}\nenable it in /skills if it is not on yet")
        return 0
    output = (args.output or Path.cwd()).resolve()
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{name}.skill"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zipped:
        for path, relative in included(folder):
            zipped.write(path, (Path(name) / relative).as_posix())
    print(f"packaged {archive} ({archive.stat().st_size / 1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
