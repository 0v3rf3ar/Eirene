#!/usr/bin/env python3
"""Render a deck to a labelled grid of slide thumbnails, for choosing layouts.

  python thumbnail.py deck.pptx [PREFIX] [--cols 4] [--width 400]

Writes PREFIX.jpg, or PREFIX-1.jpg, PREFIX-2.jpg … when there are more than 12
slides (or --per-grid), and prints the paths. Each thumbnail is labelled with its
position and slide file (for add_slide.py). PREFIX defaults to the deck's name
plus "-thumbs", so grids of different decks do not overwrite each other.

This is for picking template layouts. For checking your own output, render
full-size pages instead (see SKILL.md). Needs LibreOffice, pdftoppm and Pillow.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "office"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deck import slide_order  # noqa: E402
from soffice import convert  # noqa: E402
from workspace import opened  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Pillow is required: pip install pillow")


def font(size: int):
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> int:
    parser = argparse.ArgumentParser(description="Labelled thumbnail grid of a .pptx.")
    parser.add_argument("deck", help=".pptx file (copy a .potx to a .pptx name first)")
    parser.add_argument("prefix", nargs="?", help="output name without .jpg (default: DECK-thumbs)")
    parser.add_argument("--cols", type=int, default=4)
    parser.add_argument("--per-grid", type=int, default=12)
    parser.add_argument("--width", type=int, default=400, help="thumbnail width in pixels")
    args = parser.parse_args()
    deck = Path(args.deck)
    if deck.suffix.lower() != ".pptx":
        raise SystemExit("give a .pptx file; copy a .potx to a .pptx name first")
    if not shutil.which("pdftoppm"):
        raise SystemExit("pdftoppm (Poppler) is required")
    prefix = Path(args.prefix or deck.with_name(deck.stem + "-thumbs"))

    with opened(deck, write=False) as folder:
        visible = [Path(s["part"]).name for s in slide_order(folder) if not s["hidden"]]
        all_slides = [Path(s["part"]).name for s in slide_order(folder)]
    work = Path(tempfile.mkdtemp(prefix="thumbs-"))
    try:
        pdf = convert(deck, "pdf", work)
        subprocess.run(["pdftoppm", "-png", "-scale-to", str(args.width), str(pdf), str(work / "s")],
                       check=True, capture_output=True)
        images = sorted(work.glob("s-*.png"), key=lambda p: int(p.stem.split("-")[-1]))
        labels = visible if len(images) == len(visible) else all_slides
        if len(images) != len(labels):
            labels = [f"page {i}" for i in range(1, len(images) + 1)]
        if not images:
            raise SystemExit("LibreOffice produced no pages")
        outputs = []
        groups = [images[i:i + args.per_grid] for i in range(0, len(images), args.per_grid)]
        label_font = font(15)
        for number, group in enumerate(groups, 1):
            first = Image.open(group[0])
            w, h = first.size
            cols = min(args.cols, len(group))
            rows = (len(group) + cols - 1) // cols
            pad, caption = 14, 24
            grid = Image.new("RGB", (cols * (w + pad) + pad, rows * (h + caption + pad) + pad), "white")
            draw = ImageDraw.Draw(grid)
            for index, path in enumerate(group):
                x = pad + (index % cols) * (w + pad)
                y = pad + (index // cols) * (h + caption + pad)
                thumb = Image.open(path).convert("RGB")
                grid.paste(thumb, (x, y + caption))
                draw.rectangle([x - 1, y + caption - 1, x + thumb.width, y + caption + thumb.height], outline="#999")
                position = (number - 1) * args.per_grid + index
                draw.text((x, y + 2), f"{position + 1}. {labels[position]}", fill="#222", font=label_font)
            target = prefix.with_name(prefix.name + (f"-{number}" if len(groups) > 1 else "") + ".jpg")
            grid.save(target, quality=88)
            outputs.append(target)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    for path in outputs:
        print(path.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
