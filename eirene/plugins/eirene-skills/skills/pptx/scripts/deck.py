"""Slide bookkeeping shared by the pptx scripts."""

from __future__ import annotations

import re
from pathlib import Path

import relations
from xmlutil import P, R, children, first, load

PRESENTATION = "ppt/presentation.xml"
SLIDE_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide"
LAYOUT_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout"
NOTES_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide"
SLIDE_CT = "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"


def slide_order(folder: Path) -> list[dict]:
    """Slides in presentation order: {"part", "rid", "id", "hidden"}."""
    document = load(folder / PRESENTATION)
    rels = {r["id"]: r for r in relations.read(folder, PRESENTATION)}
    listing = first(document.documentElement, P, "sldIdLst")
    result = []
    for entry in children(listing, P, "sldId") if listing is not None else []:
        rid = entry.getAttributeNS(R, "id")
        if rid not in rels:
            continue
        part = relations.target_part(PRESENTATION, rels[rid]["target"])
        hidden = False
        path = folder / part
        if path.exists():
            hidden = load(path).documentElement.getAttribute("show") == "0"
        result.append({"part": part, "rid": rid, "id": entry.getAttribute("id"), "hidden": hidden})
    return result


def next_number(folder: Path, directory: str, stem: str) -> int:
    numbers = [int(m.group(1)) for p in (folder / directory).glob(f"{stem}*.xml")
               if (m := re.fullmatch(rf"{stem}(\d+)\.xml", p.name))]
    return max(numbers, default=0) + 1
