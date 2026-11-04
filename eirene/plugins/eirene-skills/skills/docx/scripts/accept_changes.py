#!/usr/bin/env python3
"""Accept every tracked change in a Word document.

  python accept_changes.py in.docx out.docx
  python accept_changes.py unpacked/          # in place

Insertions are kept, deletions removed, moves resolved, formatting changes
accepted, deleted table rows dropped. A deleted paragraph mark joins that
paragraph to the next one, as Word does, so a paragraph whose text and mark were
both deleted disappears instead of leaving an empty (often bulleted) line.
Comments are kept. Works on the body, headers, footers, footnotes and endnotes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
from workspace import opened  # noqa: E402
from xmlutil import W, children, elements, first, load, remove, save, unwrap  # noqa: E402

PROPERTY_CHANGES = ("rPrChange", "pPrChange", "sectPrChange", "tblPrChange", "trPrChange",
                    "tcPrChange", "tblGridChange", "tblPrExChange", "numberingChange")
RANGE_MARKERS = ("moveFromRangeStart", "moveFromRangeEnd", "moveToRangeStart", "moveToRangeEnd")
PARTS = ("document", "header", "footer", "footnotes", "endnotes")


def paragraph_mark_deleted(paragraph) -> bool:
    props = first(paragraph, W, "pPr")
    marks = first(props, W, "rPr") if props is not None else None
    return marks is not None and first(marks, W, "del") is not None


def accept(document) -> dict[str, int]:
    counts = {"inserted": 0, "deleted": 0, "joined": 0, "formatting": 0, "rows": 0}
    # Deleted table rows go first, before their cells' content is touched.
    for row in elements(document, W, "tr"):
        props = first(row, W, "trPr")
        if props is not None and first(props, W, "del") is not None:
            remove(row)
            counts["rows"] += 1
        elif props is not None:
            for mark in children(props, W, "ins"):
                remove(mark)
    # Paragraph marks: join each paragraph whose mark was deleted to the next.
    for paragraph in list(elements(document, W, "p")):
        if paragraph.parentNode is None or not paragraph_mark_deleted(paragraph):
            continue
        following = paragraph.nextSibling
        while following is not None and not (following.nodeType == following.ELEMENT_NODE
                                             and following.namespaceURI == W and following.localName == "p"):
            following = following.nextSibling
        content = [c for c in paragraph.childNodes
                   if not (c.nodeType == c.ELEMENT_NODE and c.namespaceURI == W and c.localName == "pPr")]
        if following is None:
            # Last paragraph in its container: keep it, just clear the deletion mark.
            remove(first(first(first(paragraph, W, "pPr"), W, "rPr"), W, "del"))
            continue
        anchor = first(following, W, "pPr")
        insert_at = anchor.nextSibling if anchor is not None else following.firstChild
        for node in content:
            following.insertBefore(node, insert_at)
        remove(paragraph)
        counts["joined"] += 1
    for tag in ("del", "moveFrom"):
        for node in elements(document, W, tag):
            if node.parentNode is not None:
                remove(node)
                counts["deleted"] += 1
    for tag in ("ins", "moveTo"):
        for node in elements(document, W, tag):
            if node.parentNode is None:
                continue
            if node.parentNode.namespaceURI == W and node.parentNode.localName == "rPr":
                remove(node)  # an inserted paragraph mark: nothing to keep but the mark itself
            else:
                unwrap(node)
            counts["inserted"] += 1
    for tag in PROPERTY_CHANGES:
        for node in elements(document, W, tag):
            remove(node)
            counts["formatting"] += 1
    for tag in RANGE_MARKERS + ("cellIns", "cellDel", "cellMerge"):
        for node in elements(document, W, tag):
            remove(node)
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Accept all tracked changes in a .docx.")
    parser.add_argument("source", help=".docx or unpacked folder")
    parser.add_argument("output", nargs="?", help="output .docx (default: in place)")
    args = parser.parse_args()
    totals: dict[str, int] = {}
    with opened(args.source, args.output) as folder:
        for path in sorted((folder / "word").glob("*.xml")):
            if path.stem.rstrip("0123456789") not in PARTS:
                continue
            document = load(path)
            for key, value in accept(document).items():
                totals[key] = totals.get(key, 0) + value
            save(document, path)
        settings = folder / "word" / "settings.xml"
        if settings.exists():
            document = load(settings)
            for node in elements(document, W, "trackRevisions"):
                remove(node)
            save(document, settings)
    print("accepted: " + ", ".join(f"{v} {k}" for k, v in totals.items() if v) if any(totals.values())
          else "no tracked changes found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
