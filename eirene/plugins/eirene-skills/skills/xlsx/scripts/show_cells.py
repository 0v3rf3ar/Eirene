#!/usr/bin/env python3
"""Show what is in a workbook, cell by cell, with formulas and cached values.

  python show_cells.py book.xlsx [--sheet NAME] [--range A1:H40] [--formulas-only]

Prints each sheet's used range, merged cells, and every non-empty cell as
  B7  =SUM(B2:B6)  →  1250
so you can plan edits by coordinate. Uses only Python's standard library, so it
works before openpyxl or pandas are installed. A formula with no cached value
shows "→ (not calculated)"; run recalc.py to fill those in.
"""

from __future__ import annotations

import argparse
import posixpath
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

X = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL = "http://schemas.openxmlformats.org/package/2006/relationships"


def col_number(letters: str) -> int:
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch) - 64
    return value


def split(ref: str) -> tuple[int, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", ref)
    return (col_number(match.group(1)), int(match.group(2))) if match else (0, 0)


def shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(f"{{{X}}}t")) for si in root.findall(f"{{{X}}}si")]


def sheets(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels.findall(f"{{{REL}}}Relationship")}
    result = []
    for sheet in workbook.iter(f"{{{X}}}sheet"):
        target = targets.get(sheet.get(f"{{{R}}}id"), "")
        part = target.lstrip("/") if target.startswith("/") else posixpath.normpath(posixpath.join("xl", target))
        result.append((sheet.get("name"), part, sheet.get("state", "visible")))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Cell-by-cell view of an .xlsx/.xlsm.")
    parser.add_argument("workbook")
    parser.add_argument("--sheet", help="only this sheet")
    parser.add_argument("--range", help="only cells inside this range, e.g. A1:H40")
    parser.add_argument("--formulas-only", action="store_true", help="only cells with formulas")
    parser.add_argument("--max-cells", type=int, default=400, help="cells to print per sheet (default 400)")
    args = parser.parse_args()
    bounds = None
    if args.range:
        start, _, end = args.range.upper().partition(":")
        bounds = (split(start), split(end or start))
    with zipfile.ZipFile(args.workbook) as archive:
        strings = shared_strings(archive)
        for name, part, state in sheets(archive):
            if args.sheet and name != args.sheet:
                continue
            root = ET.fromstring(archive.read(part))
            dimension = root.find(f"{{{X}}}dimension")
            merged = [m.get("ref") for m in root.iter(f"{{{X}}}mergeCell")]
            print(f"## {name}" + (f" ({state})" if state != "visible" else "")
                  + (f" — used range {dimension.get('ref')}" if dimension is not None else ""))
            if merged:
                print("merged: " + ", ".join(merged[:40]) + (" …" if len(merged) > 40 else ""))
            shown = 0
            for cell in root.iter(f"{{{X}}}c"):
                ref = cell.get("r", "")
                if bounds:
                    col, row = split(ref)
                    (c1, r1), (c2, r2) = bounds
                    if not (c1 <= col <= c2 and r1 <= row <= r2):
                        continue
                formula = cell.find(f"{{{X}}}f")
                value = cell.findtext(f"{{{X}}}v")
                kind = cell.get("t")
                if kind == "s" and value is not None and value.isdigit() and int(value) < len(strings):
                    value = strings[int(value)]
                elif kind == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iter(f"{{{X}}}t"))
                elif kind == "b" and value is not None:
                    value = "TRUE" if value == "1" else "FALSE"
                if formula is None and args.formulas_only:
                    continue
                if formula is None and value in (None, ""):
                    continue
                text = ""
                if formula is not None:
                    body = formula.text or (f"(shared formula {formula.get('si')})" if formula.get("t") == "shared" else "")
                    text = f"={body}  →  " + (repr(value) if value not in (None, "") else "(not calculated)")
                else:
                    text = repr(value)
                print(f"  {ref:<8} {text}")
                shown += 1
                if shown >= args.max_cells:
                    print(f"  … more cells; narrow with --range")
                    break
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
