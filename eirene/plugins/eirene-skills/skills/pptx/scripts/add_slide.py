#!/usr/bin/env python3
"""Add a slide by duplicating a slide or starting from a layout.

  python add_slide.py unpacked/ slide2.xml [--after slide5.xml]
  python add_slide.py unpacked/ slideLayout3.xml
  python add_slide.py deck.pptx slide2.xml -o out.pptx

From a slide: copies it with all its links (images, charts, layout); speaker
notes are not copied. Charts, SmartArt and embedded objects stay shared with
the source slide — editing one changes both. From a layout: makes a slide with
that layout's empty placeholders. The new slide is registered in the content
types, the presentation's relationships and <p:sldIdLst> (at the end, or after
--after). Prints the new slide's path.

With a packed .pptx, pass -o; without it the input file is rewritten in place.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import relations  # noqa: E402
from deck import (LAYOUT_TYPE, NOTES_TYPE, PRESENTATION, SLIDE_CT, SLIDE_TYPE, next_number,  # noqa: E402
                  slide_order)
from workspace import opened  # noqa: E402
from xmlutil import A, P, R, REL, children, first, load, parse_bytes, save  # noqa: E402

SLIDE_TEMPLATE = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                  f'<p:sld xmlns:a="{A}" xmlns:r="{R}" xmlns:p="{P}"><p:cSld><p:spTree>'
                  '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
                  '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
                  '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
                  '</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>')


def from_layout(folder: Path, layout_part: str, new_part: str) -> None:
    layout = load(folder / layout_part)
    slide = parse_bytes(SLIDE_TEMPLATE.encode())
    tree = slide.getElementsByTagNameNS(P, "spTree")[0]
    for shape in layout.getElementsByTagNameNS(P, "sp"):
        nv = first(shape, P, "nvSpPr")
        nvpr = first(nv, P, "nvPr") if nv is not None else None
        if nvpr is None or first(nvpr, P, "ph") is None:
            continue
        kind = first(nvpr, P, "ph").getAttribute("type")
        if kind in ("dt", "ftr", "sldNum"):
            continue  # date, footer and number come from the master when switched on
        copy = slide.importNode(shape, True)
        for child in children(copy):
            if child.localName in ("spPr", "txBody", "style"):
                copy.removeChild(child)
        copy.appendChild(slide.createElementNS(P, "p:spPr"))
        body = slide.createElementNS(P, "p:txBody")
        for name in ("a:bodyPr", "a:lstStyle", "a:p"):
            body.appendChild(slide.createElementNS(A, name))
        copy.appendChild(body)
        tree.appendChild(copy)
    save(slide, folder / new_part)
    relations.add(folder, new_part, LAYOUT_TYPE, layout_part)


def from_slide(folder: Path, source_part: str, new_part: str) -> None:
    shutil.copyfile(folder / source_part, folder / new_part)
    source_rels = relations.rels_file(folder, source_part)
    if source_rels.exists():
        document = load(source_rels)
        for rel in children(document.documentElement, REL, "Relationship"):
            if rel.getAttribute("Type") == NOTES_TYPE:
                document.documentElement.removeChild(rel)
        target = relations.rels_file(folder, new_part)
        target.parent.mkdir(parents=True, exist_ok=True)
        save(document, target)


def register(folder: Path, new_part: str, after: str | None) -> None:
    relations.set_override(folder, new_part, SLIDE_CT)
    rid = relations.add(folder, PRESENTATION, SLIDE_TYPE, new_part)
    document = load(folder / PRESENTATION)
    root = document.documentElement
    listing = first(root, P, "sldIdLst")
    if listing is None:
        listing = document.createElementNS(P, f"{root.prefix}:sldIdLst" if root.prefix else "sldIdLst")
        masters = first(root, P, "notesMasterIdLst") or first(root, P, "sldMasterIdLst")
        root.insertBefore(listing, masters.nextSibling if masters is not None else root.firstChild)
    entries = children(listing, P, "sldId")
    new_id = max([int(e.getAttribute("id")) for e in entries] + [255]) + 1
    entry = document.createElementNS(P, f"{root.prefix}:sldId" if root.prefix else "sldId")
    entry.setAttribute("id", str(new_id))
    entry.setAttributeNS(R, "r:id", rid)
    position = None
    if after:
        order = {s["rid"]: s["part"] for s in slide_order(folder)}
        for existing in entries:
            if order.get(existing.getAttributeNS(R, "id"), "").endswith("/" + after):
                position = existing.nextSibling
                break
        else:
            raise SystemExit(f"--after {after}: that slide is not in the slide list")
    listing.insertBefore(entry, position)
    save(document, folder / PRESENTATION)


def main() -> int:
    parser = argparse.ArgumentParser(description="Duplicate a slide or add one from a layout.")
    parser.add_argument("source", help="unpacked folder or .pptx")
    parser.add_argument("template", help="slideN.xml to duplicate, or slideLayoutN.xml to start from")
    parser.add_argument("--after", help="insert after this slide file (default: at the end)")
    parser.add_argument("-o", "--output", help="output .pptx (packed input only; default: in place)")
    args = parser.parse_args()
    name = Path(args.template).name
    with opened(args.source, args.output) as folder:
        new_part = f"ppt/slides/slide{next_number(folder, 'ppt/slides', 'slide')}.xml"
        (folder / "ppt/slides").mkdir(parents=True, exist_ok=True)
        if name.startswith("slideLayout"):
            layout = f"ppt/slideLayouts/{name}"
            if not (folder / layout).exists():
                raise SystemExit(f"{layout} does not exist")
            from_layout(folder, layout, new_part)
        else:
            source = f"ppt/slides/{name}"
            if not (folder / source).exists():
                raise SystemExit(f"{source} does not exist")
            from_slide(folder, source, new_part)
        register(folder, new_part, Path(args.after).name if args.after else None)
    print(f"Created {new_part} from {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
