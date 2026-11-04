"""Check an animated GIF against the limits that chat apps such as Slack apply."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

# Slack accepts custom emoji up to 128 KB and recommends 128x128; message GIFs
# work best at or under 480 px and a few megabytes.
EMOJI_MAX_BYTES = 128 * 1024
EMOJI_SIZE = 128
MESSAGE_MAX_SIDE = 480
MESSAGE_MAX_BYTES = 5 * 1024 * 1024


def inspect(path: str | Path) -> dict:
    path = Path(path)
    with Image.open(path) as image:
        frames, total = 0, 0
        try:
            while True:
                frames += 1
                total += image.info.get("duration", 100)
                image.seek(image.tell() + 1)
        except EOFError:
            pass
        return {"path": str(path), "width": image.width, "height": image.height, "frames": frames,
                "seconds": total / 1000, "bytes": path.stat().st_size,
                "fps": round(frames / (total / 1000), 1) if total else 0.0,
                "loop": image.info.get("loop")}


def validate_gif(path: str | Path, is_emoji: bool = True, verbose: bool = True) -> tuple[bool, dict]:
    """(passes, info). info has the measurements plus "problems" and "warnings" lists."""
    info = inspect(path)
    problems: list[str] = []
    warnings: list[str] = []
    if is_emoji:
        if info["bytes"] > EMOJI_MAX_BYTES:
            problems.append(f"{info['bytes'] / 1024:.0f} KB is over the 128 KB emoji limit")
        if (info["width"], info["height"]) != (EMOJI_SIZE, EMOJI_SIZE):
            warnings.append(f"{info['width']}x{info['height']}; emoji look best at 128x128")
        if info["seconds"] > 3:
            warnings.append(f"{info['seconds']:.1f}s long; keep emoji under about 3 seconds")
    else:
        if max(info["width"], info["height"]) > MESSAGE_MAX_SIDE:
            warnings.append(f"{info['width']}x{info['height']}; 480 px or less loads faster")
        if info["bytes"] > MESSAGE_MAX_BYTES:
            problems.append(f"{info['bytes'] / 1048576:.1f} MB; keep message GIFs under 5 MB")
    if info["frames"] < 2:
        warnings.append("only one frame; it will not animate")
    if info["loop"] is None:
        warnings.append("no loop setting; some apps play it once")
    if info["fps"] > 30:
        warnings.append(f"{info['fps']} fps; above 30 fps adds size without looking smoother")
    info["problems"], info["warnings"] = problems, warnings
    passes = not problems
    if verbose:
        kind = "emoji" if is_emoji else "message GIF"
        print(f"{info['path']}: {info['width']}x{info['height']}, {info['frames']} frames, "
              f"{info['seconds']:.2f}s, {info['fps']} fps, {info['bytes'] / 1024:.1f} KB")
        for line in problems:
            print(f"  problem: {line}")
        for line in warnings:
            print(f"  note: {line}")
        print(f"  {'ready' if passes else 'not ready'} as a Slack {kind}")
    return passes, info


def is_slack_ready(path: str | Path, is_emoji: bool = True) -> bool:
    return validate_gif(path, is_emoji=is_emoji, verbose=False)[0]


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("usage: python -m core.validators FILE.gif [--message]")
        sys.exit(0 if len(sys.argv) > 1 else 2)
    ok, _ = validate_gif(sys.argv[1], is_emoji="--message" not in sys.argv[2:])
    sys.exit(0 if ok else 1)
