#!/usr/bin/env python3
"""Remove slides that are not in the slide list, and every part nothing uses.

  python clean.py unpacked/
  python clean.py deck.pptx -o cleaned.pptx

Run it after <p:sldIdLst> in ppt/presentation.xml is final: slides missing from
the list are deleted (with their notes), then any part that no relationship
reaches any more — media, charts, embedded files, layouts nobody uses stay if a
master still links them — is removed with its relationships and content type.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relations  # noqa: E402
from deck import PRESENTATION, SLIDE_TYPE, slide_order  # noqa: E402
from workspace import opened  # noqa: E402


def reachable(folder: Path) -> set[str]:
    seen: set[str] = set()
    queue = [relations.target_part("", r["target"]) for r in relations.read(folder, "")
             if r["mode"] != "External"]
    while queue:
        part = queue.pop()
        if part in seen or not (folder / part).exists():
            continue
        seen.add(part)
        for rel in relations.read(folder, part):
            if rel["mode"] != "External":
                queue.append(relations.target_part(part, rel["target"]))
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description="Delete unlisted slides and unreferenced parts from a .pptx.")
    parser.add_argument("source", help="unpacked folder or .pptx")
    parser.add_argument("-o", "--output", help="output .pptx (packed input only; default: in place)")
    args = parser.parse_args()
    removed: list[str] = []
    with opened(args.source, args.output) as folder:
        listed = {s["rid"] for s in slide_order(folder)}
        stale = {r["id"] for r in relations.read(folder, PRESENTATION)
                 if r["type"] == SLIDE_TYPE and r["id"] not in listed}
        relations.remove_ids(folder, PRESENTATION, stale)
        keep = reachable(folder)
        for path in sorted(folder.rglob("*")):
            if not path.is_file():
                continue
            part = path.relative_to(folder).as_posix()
            if part == "[Content_Types].xml" or part.endswith(".rels"):
                continue
            if part not in keep:
                path.unlink()
                rels = relations.rels_file(folder, part)
                if rels.exists():
                    rels.unlink()
                relations.set_override(folder, part, None)
                removed.append(part)
        for rels in folder.rglob("*.rels"):
            owner = rels.parent.parent / rels.name[:-5]
            if rels.parent.name == "_rels" and rels.parent.parent != folder and not owner.exists():
                rels.unlink()
    print(f"removed {len(removed)} parts" + (":\n  " + "\n  ".join(removed) if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
