#!/usr/bin/env python3
"""Print a deck's text slide by slide, in presentation order, with speaker notes.

  python extract_text.py deck.pptx [--no-notes]

Each slide starts with "<!-- Slide N: slideX.xml -->" (marked hidden when it is).
Text appears in shape order; tables print as rows separated by " | ".
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relations  # noqa: E402
from deck import NOTES_TYPE, slide_order  # noqa: E402
from workspace import opened  # noqa: E402
from xmlutil import A, P, children, elements, load, text_of  # noqa: E402


def paragraphs(container) -> list[str]:
    lines = []
    for paragraph in elements(container, A, "p"):
        line = "".join(text_of(t) for t in elements(paragraph, A, "t"))
        if line.strip():
            lines.append(line)
    return lines


def slide_text(document) -> list[str]:
    lines: list[str] = []
    tree = document.getElementsByTagNameNS(P, "spTree")[0]

    def walk(node) -> None:
        for child in children(node):
            if child.localName == "grpSp":
                walk(child)
            elif child.localName == "sp":
                lines.extend(paragraphs(child))
            elif child.localName == "graphicFrame":
                for row in elements(child, A, "tr"):
                    cells = [" ".join(paragraphs(cell)) for cell in children(row, A, "tc")]
                    if any(cells):
                        lines.append(" | ".join(cells))
    walk(tree)
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump the text of a .pptx.")
    parser.add_argument("source", help=".pptx or unpacked folder")
    parser.add_argument("--no-notes", action="store_true", help="leave out speaker notes")
    args = parser.parse_args()
    with opened(args.source, write=False) as folder:
        for number, slide in enumerate(slide_order(folder), 1):
            label = Path(slide["part"]).name + (", hidden" if slide["hidden"] else "")
            print(f"<!-- Slide {number}: {label} -->")
            for line in slide_text(load(folder / slide["part"])):
                print(line)
            if not args.no_notes:
                for rel in relations.read(folder, slide["part"]):
                    if rel["type"] == NOTES_TYPE:
                        notes = load(folder / relations.target_part(slide["part"], rel["target"]))
                        body = [line for line in slide_text(notes) if not line.strip().isdigit()]
                        if body:
                            print("Notes: " + " / ".join(body))
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
