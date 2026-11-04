#!/usr/bin/env python3
"""Download open-licensed font families from Google Fonts as .ttf files.

  python fonts.py --list
  python fonts.py "Instrument Serif" "Work Sans:300,600" --dest fonts

A family can carry weights after a colon (default 400). Italic styles are
requested with an "i" suffix, for example "Lora:400,400i,700". The script prints
each saved file's path. Files are named Family-Weight[Italic].ttf, and a
LICENSE note is written next to them.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://fonts.googleapis.com/css2"
# A plain client name makes the API answer with TrueType files rather than WOFF2.
AGENT = "eirene-fonts/1.0"

SUGGESTED = {
    "display serif": ["Instrument Serif", "Gloock", "Young Serif", "Italiana", "Libre Baskerville"],
    "text serif": ["Crimson Pro", "Lora", "IBM Plex Serif"],
    "grotesque / sans": ["Work Sans", "Instrument Sans", "Bricolage Grotesque", "Outfit", "Jura"],
    "condensed / poster": ["Big Shoulders Display", "Boldonse", "Erica One", "Smooch Sans", "Tektur"],
    "monospace": ["IBM Plex Mono", "JetBrains Mono", "DM Mono", "Geist Mono", "Red Hat Mono"],
    "small caps / deco": ["Arsenal SC", "Poiret One", "National Park"],
    "hand / pixel": ["Nothing You Could Do", "Pixelify Sans", "Silkscreen"],
}


def parse(spec: str) -> tuple[str, list[tuple[int, bool]]]:
    family, _, raw = spec.partition(":")
    styles = []
    for part in (raw or "400").split(","):
        match = re.fullmatch(r"\s*(\d{3})(i?)\s*", part)
        if not match:
            raise SystemExit(f"bad weight {part!r} in {spec!r}; use e.g. 300,400i,700")
        styles.append((int(match.group(1)), bool(match.group(2))))
    return family.strip(), sorted(set(styles))


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def download(family: str, styles: list[tuple[int, bool]], dest: Path) -> list[Path]:
    axes = "ital,wght@" + ";".join(f"{int(italic)},{weight}" for weight, italic in styles)
    query = urllib.parse.urlencode({"family": f"{family}:{axes}"}, safe=":,;@")
    try:
        css = fetch(f"{API}?{query}").decode()
    except Exception:
        # Families without an italic axis reject the ital form; retry upright only.
        weights = ";".join(str(weight) for weight, italic in styles if not italic) or "400"
        query = urllib.parse.urlencode({"family": f"{family}:wght@{weights}"}, safe=":,;@")
        try:
            css = fetch(f"{API}?{query}").decode()
        except Exception as exc:
            raise SystemExit(f"{family}: not found on Google Fonts ({exc})")
    saved = []
    for block in re.findall(r"@font-face\s*{(.*?)}", css, re.S):
        style = re.search(r"font-style:\s*(\w+)", block)
        weight = re.search(r"font-weight:\s*(\d+)", block)
        url = re.search(r"url\((https://[^)]+)\)", block)
        if not (weight and url):
            continue
        italic = bool(style and style.group(1) == "italic")
        name = f"{family.replace(' ', '')}-{weight.group(1)}{'Italic' if italic else ''}.ttf"
        path = dest / name
        if not path.exists():
            path.write_bytes(fetch(url.group(1)))
        if path not in saved:
            saved.append(path)
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Google Fonts families as .ttf.")
    parser.add_argument("families", nargs="*", help='family names, e.g. "Work Sans:300,700"')
    parser.add_argument("--dest", type=Path, default=Path("fonts"), help="folder to save into (default: fonts)")
    parser.add_argument("--list", action="store_true", help="show suggested families")
    args = parser.parse_args()
    if args.list or not args.families:
        for group, names in SUGGESTED.items():
            print(f"{group}: {', '.join(names)}")
        print("\nAny Google Fonts family works: https://fonts.google.com")
        return 0
    args.dest.mkdir(parents=True, exist_ok=True)
    for spec in args.families:
        family, styles = parse(spec)
        for path in download(family, styles, args.dest):
            print(path.resolve())
    note = args.dest / "LICENSE-fonts.txt"
    if not note.exists():
        note.write_text("These fonts come from Google Fonts and are distributed under the SIL Open "
                        "Font License or Apache License 2.0. See https://fonts.google.com/attribution "
                        "and each family's page for its licence.\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
