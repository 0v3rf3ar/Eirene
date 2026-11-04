#!/usr/bin/env python3
"""Render PDF pages to PNG images and report their sizes.

  python pdf_to_images.py file.pdf out_dir [--dpi 150] [--pages 1-3] [--max 2000]

Writes out_dir/page_1.png, page_2.png, … and prints each image's pixel size and
the page size in points, which you need to convert between image and PDF
coordinates. Uses Poppler's pdftoppm.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


def page_sizes(pdf: Path) -> dict[int, tuple[float, float]]:
    if not shutil.which("pdfinfo"):
        return {}
    out = subprocess.run(["pdfinfo", "-f", "1", "-l", "100000", str(pdf)], capture_output=True, text=True).stdout
    return {int(m.group(1)): (float(m.group(2)), float(m.group(3)))
            for m in re.finditer(r"Page\s+(\d+) size:\s+([\d.]+) x ([\d.]+)", out)}


def main() -> int:
    parser = argparse.ArgumentParser(description="PDF pages to PNG with pdftoppm.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--pages", help="range such as 2 or 1-4")
    parser.add_argument("--max", type=int, default=2000, help="longest side in pixels (default 2000)")
    args = parser.parse_args()
    if not shutil.which("pdftoppm"):
        raise SystemExit("pdftoppm (Poppler) is required")
    args.out.mkdir(parents=True, exist_ok=True)
    command = ["pdftoppm", "-png", "-r", str(args.dpi), "-scale-to", str(args.max)]
    if args.pages:
        first, _, last = args.pages.partition("-")
        command += ["-f", first, "-l", last or first]
    prefix = args.out / "page"
    result = subprocess.run(command + [str(args.pdf), str(prefix)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or "pdftoppm failed")
    sizes = page_sizes(args.pdf)
    for path in sorted(args.out.glob("page-*.png"), key=lambda p: int(p.stem.split("-")[-1])):
        number = int(path.stem.split("-")[-1])
        target = args.out / f"page_{number}.png"
        path.replace(target)
        width = height = None
        try:
            from PIL import Image
            with Image.open(target) as image:
                width, height = image.size
        except ImportError:
            pass
        points = sizes.get(number)
        detail = f"{width}x{height} px" if width else ""
        if points:
            detail += f", page {points[0]:g}x{points[1]:g} pt"
        print(f"{target}  {detail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
