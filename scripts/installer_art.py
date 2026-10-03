"""Regenerate embedded installer portraits from img/Eirene.png (needs Pillow)."""
from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DOTS = ((0, 0, 0), (0, 1, 1), (0, 2, 2), (1, 0, 3),
        (1, 1, 4), (1, 2, 5), (0, 3, 6), (1, 3, 7))


def portrait() -> str:
    source = Image.open(ROOT / "img/Eirene.png").convert("RGBA")
    background = Image.new("RGBA", source.size, "black")
    background.alpha_composite(source)
    gray = background.convert("L").resize((96, 80), Image.Resampling.LANCZOS)
    rows = []
    for y in range(0, gray.height, 4):
        row = ""
        for x in range(0, gray.width, 2):
            bits = sum(1 << bit for dx, dy, bit in DOTS
                       if gray.getpixel((x + dx, y + dy)) > 100)
            row += chr(0x2800 + bits) if bits else " "
        rows.append(row.rstrip())
    return "\n".join(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check without rewriting")
    args = parser.parse_args()
    art = portrait()
    escaped = "".join(f"\\u{ord(c):04x}" if ord(c) > 127 else c for c in art)
    patterns = {
        "install.sh": (r"(?<=cat <<'EIRENE_ART'\n).*?(?=\nEIRENE_ART)", art),
        "install.ps1": (r"(?<=\$portrait = \[regex\]::Unescape\(@'\n).*?(?=\n'@\))", escaped),
    }
    changed = []
    for name, (pattern, replacement) in patterns.items():
        path = ROOT / name
        original = path.read_text()
        updated, count = re.subn(pattern, lambda _: replacement, original, flags=re.S)
        if count != 1:
            raise SystemExit(f"Could not find the portrait in {name}")
        if updated != original:
            changed.append(name)
            if not args.check:
                path.write_text(updated)
    if args.check and changed:
        print("Portrait needs regeneration: " + ", ".join(changed))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
