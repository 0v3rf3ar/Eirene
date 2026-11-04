#!/usr/bin/env python3
"""Check the boxes in fields.json before filling a non-fillable form.

  python check_boxes.py fields.json

Reports entry boxes that overlap each other or a label, boxes too short for
their font size, and fields on pages that are not described. Exit status 1 when
anything is wrong. Coordinates are [x0, top, x1, bottom] with a top-left origin.
"""

from __future__ import annotations

import json
import sys


def overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 0 if len(sys.argv) == 2 else 2
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    pages = {p["page_number"]: p for p in data.get("pages", [])}
    fields = data.get("form_fields", [])
    problems = []
    boxes = []
    for index, field in enumerate(fields):
        name = field.get("description") or field.get("field_label") or f"field {index + 1}"
        page = field.get("page_number")
        if page not in pages:
            problems.append(f"{name}: page {page} is missing from \"pages\"")
        info = pages.get(page, {})
        scale = 1.0
        if info.get("image_height") and not info.get("pdf_height"):
            scale = 72 / 150  # rough pixels-to-points at the default 150 dpi, for the size check only
        entry = field.get("entry_bounding_box")
        if not (isinstance(entry, list) and len(entry) == 4 and entry[2] > entry[0] and entry[3] > entry[1]):
            problems.append(f"{name}: entry_bounding_box must be [x0, top, x1, bottom] with x1 > x0, bottom > top")
            continue
        size = (field.get("entry_text") or {}).get("font_size", 10)
        height = (entry[3] - entry[1]) * scale
        if (field.get("entry_text") or {}).get("text") and height < size * 0.9:
            problems.append(f"{name}: box is {height:.1f} pt tall, too short for {size} pt text; "
                            "make it taller or the font smaller")
        boxes.append((page, name, "entry", entry))
        label = field.get("label_bounding_box")
        if isinstance(label, list) and len(label) == 4:
            boxes.append((page, name, "label", label))
    for i, (page_a, name_a, kind_a, box_a) in enumerate(boxes):
        for page_b, name_b, kind_b, box_b in boxes[i + 1:]:
            if page_a != page_b or (kind_a == kind_b == "label"):
                continue
            if name_a == name_b and {kind_a, kind_b} == {"entry", "label"}:
                if overlap(box_a, box_b):
                    problems.append(f"{name_a}: the entry box overlaps its own label; start it after the label")
                continue
            if overlap(box_a, box_b):
                problems.append(f"page {page_a}: {kind_a} of {name_a!r} overlaps {kind_b} of {name_b!r}")
    for line in problems:
        print(f"problem: {line}")
    print(f"{len(fields)} fields checked, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
