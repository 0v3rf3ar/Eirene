#!/usr/bin/env python3
"""Find the labels, lines and checkboxes of a PDF form that has no fillable fields.

  python form_structure.py form.pdf form_structure.json

Writes, per page (PDF points, y = 0 at the TOP of the page, growing downwards):
  labels          every word: text, x0, top, x1, bottom
  lines           horizontal rules: x0, x1, y
  checkboxes      small squares: x0, top, x1, bottom, center
  row_boundaries  distinct y positions of the horizontal rules
plus pdf_width and pdf_height. Uses pdfplumber when installed (pip install
pdfplumber); otherwise falls back to Poppler's pdftotext, which finds words but
not lines or boxes. A scanned form yields no labels: estimate from the page
images instead (see forms.md).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET


def with_pdfplumber(path: str) -> list[dict]:
    import pdfplumber

    pages = []
    with pdfplumber.open(path) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=True)
            labels = [{"text": w["text"], "x0": round(w["x0"], 1), "top": round(w["top"], 1),
                       "x1": round(w["x1"], 1), "bottom": round(w["bottom"], 1)} for w in words]
            lines = []
            for line in page.lines:
                if abs(line["top"] - line["bottom"]) < 1.5 and line["x1"] - line["x0"] > 15:
                    lines.append({"x0": round(line["x0"], 1), "x1": round(line["x1"], 1), "y": round(line["top"], 1)})
            boxes = []
            for rect in page.rects:
                w, h = rect["x1"] - rect["x0"], rect["bottom"] - rect["top"]
                if h < 1.5 and w > 15:
                    lines.append({"x0": round(rect["x0"], 1), "x1": round(rect["x1"], 1), "y": round(rect["top"], 1)})
                elif 4 <= w <= 20 and 4 <= h <= 20 and abs(w - h) <= 2.5:
                    boxes.append({"x0": round(rect["x0"], 1), "top": round(rect["top"], 1),
                                  "x1": round(rect["x1"], 1), "bottom": round(rect["bottom"], 1),
                                  "center": [round((rect["x0"] + rect["x1"]) / 2, 1),
                                             round((rect["top"] + rect["bottom"]) / 2, 1)]})
            rows = sorted({round(l["y"]) for l in lines})
            pages.append({"page_number": number, "pdf_width": round(page.width, 2), "pdf_height": round(page.height, 2),
                          "labels": labels, "lines": lines, "checkboxes": boxes, "row_boundaries": rows})
    return pages


def with_pdftotext(path: str) -> list[dict]:
    if not shutil.which("pdftotext"):
        raise SystemExit("install pdfplumber (pip install pdfplumber) or Poppler's pdftotext")
    out = subprocess.run(["pdftotext", "-bbox", path, "-"], capture_output=True, text=True, check=True).stdout
    root = ET.fromstring(out.replace('xmlns="http://www.w3.org/1999/xhtml"', ""))
    pages = []
    for number, page in enumerate(root.iter("page"), 1):
        labels = [{"text": w.text or "", "x0": round(float(w.get("xMin")), 1), "top": round(float(w.get("yMin")), 1),
                   "x1": round(float(w.get("xMax")), 1), "bottom": round(float(w.get("yMax")), 1)}
                  for w in page.iter("word")]
        pages.append({"page_number": number, "pdf_width": float(page.get("width")),
                      "pdf_height": float(page.get("height")), "labels": labels, "lines": [],
                      "checkboxes": [], "row_boundaries": [],
                      "note": "pdfplumber is not installed: lines and checkboxes were not detected"})
    return pages


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip())
        return 2
    try:
        pages = with_pdfplumber(sys.argv[1])
    except ImportError:
        pages = with_pdftotext(sys.argv[1])
    with open(sys.argv[2], "w", encoding="utf-8") as handle:
        json.dump({"pages": pages}, handle, indent=1)
    for page in pages:
        print(f"page {page['page_number']}: {len(page['labels'])} labels, {len(page['lines'])} lines, "
              f"{len(page['checkboxes'])} checkboxes")
    if not any(page["labels"] for page in pages):
        print("no text found: the form is probably scanned; use the visual approach in forms.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
