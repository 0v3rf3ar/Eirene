"""Regenerate the bundled pixel grid from img/Eirene.png (development only)."""
from pathlib import Path
import struct
import zlib

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    with Image.open(ROOT / "img" / "Eirene.png") as image:
        rgba = image.convert("RGBA")
        black = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        black.alpha_composite(rgba)
        grid = black.convert("L").resize((256, 256), Image.Resampling.LANCZOS)
        data = struct.pack(">HH", *grid.size) + grid.tobytes()
    (ROOT / "eirene" / "ui" / "logo.gray.zlib").write_bytes(zlib.compress(data, 9))


if __name__ == "__main__":
    main()
