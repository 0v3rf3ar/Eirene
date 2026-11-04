"""Draw Eirene's small animation frames as deltas over idle.png.

Each frame is stored as only the pixels that differ from its base picture,
cropped to their bounding box. The PNG's ``base`` and ``offset`` text chunks
say where to paste it. A full 128x128 frame costs about 3.5 KB; a delta is a
few hundred bytes, and every frame registers exactly with the idle pose.

idle-blink.png is not drawn here: it is the lens area of the original
generated blink frame, kept as a delta over idle.png.

Run from the repository root:  python scripts/companion_frames.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, PngImagePlugin

ASSETS = Path(__file__).resolve().parents[1] / "eirene" / "ui" / "companion_assets"

DARK = (15, 12, 15, 252)
WHITE = (250, 247, 246, 253)
GLARE = (238, 231, 229, 253)
# Lens interiors of idle.png as ellipses: centre x, centre y, radius x, radius y.
LENSES = ((45, 63, 5.5, 4.6), (67.5, 63, 5.5, 4.6))


def inside(lens, x, y) -> bool:
    cx, cy, rx, ry = lens
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1


def glint(img, step: int):
    """A diagonal shine crossing both lenses, left to right."""
    for lens in LENSES:
        cx, cy, rx, ry = lens
        c = round(cx - cy) + (-5, 0, 5)[step]
        for x in range(int(cx - rx), int(cx + rx) + 1):
            for y in range(int(cy - ry), int(cy + ry) + 1):
                if x - y in (c, c + 1) and inside(lens, x, y):
                    img.putpixel((x, y), GLARE)


NOTE = [
    "..XX.",
    "..X.X",
    "..X..",
    "XXX..",
    "XXX..",
]


def note(img, left: int, top: int, scale: int = 2):
    """A chunky outlined music note, matching the ? and zzz marks."""
    fill = {(left + i * scale + dx, top + j * scale + dy)
            for j, row in enumerate(NOTE) for i, ch in enumerate(row) if ch == "X"
            for dx in range(scale) for dy in range(scale)}
    outline = {(x + dx, y + dy) for x, y in fill
               for dx in range(-scale, scale + 1) for dy in range(-scale, scale + 1)} - fill
    for p in outline:
        img.putpixel(p, DARK)
    for p in fill:
        img.putpixel(p, WHITE)


def save_delta(frame, base_name: str, name: str):
    base = Image.open(ASSETS / base_name).convert("RGBA")
    changed = Image.new("L", frame.size)
    changed.putdata([255 if a != b else 0
                     for a, b in zip(frame.getdata(), base.getdata())])
    box = changed.getbbox()
    assert box, f"{name} does not differ from {base_name}"
    assert all(frame.getpixel(p)[3] >= 128 for p in
               ((x, y) for x in range(box[0], box[2]) for y in range(box[1], box[3]))
               if changed.getpixel(p)), "deltas only add or recolor pixels"
    delta = Image.new("RGBA", frame.size)
    delta.paste(frame, mask=changed)
    delta = delta.crop(box)
    colors = [(0, 0, 0, 0)] + sorted({c for _, c in delta.getcolors(256)} - {(0, 0, 0, 0)})
    index = {c: i for i, c in enumerate(colors)}
    out = Image.new("P", delta.size)
    out.putdata([index[p] for p in delta.getdata()])
    out.putpalette([v for c in colors for v in c[:3]])
    meta = PngImagePlugin.PngInfo()
    for key in ("Title", "Author", "Description", "Source"):
        if key in base.info:
            meta.add_text(key, base.info[key])
    meta.add_text("base", base_name)
    meta.add_text("offset", f"{box[0]},{box[1]}")
    out.save(ASSETS / name, optimize=True, pnginfo=meta,
             transparency=bytes(c[3] for c in colors))


def main():
    idle = Image.open(ASSETS / "idle.png").convert("RGBA")

    for step in range(3):
        frame = idle.copy()
        glint(frame, step)
        save_delta(frame, "idle.png", f"glint-{step + 1}.png")

    # Humming along to her earphones: a note drifts up beside her head.
    for step, (left, top) in enumerate(((96, 34), (99, 26), (102, 18))):
        frame = idle.copy()
        note(frame, left, top)
        save_delta(frame, "idle.png", f"hum-{step + 1}.png")


if __name__ == "__main__":
    main()
