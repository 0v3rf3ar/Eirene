#!/usr/bin/env python3
"""Draw the boxes from fields.json on a page image, to check them by eye.

  python validation_image.py page_1.png fields.json 1 checked_1.png

Entry boxes are red, label boxes blue, each numbered as in fields.json. Boxes
in PDF points (pdf_width/pdf_height) are scaled to the image.
"""

from __future__ import annotations

import json
import sys

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Pillow is required: pip install pillow")


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__.strip())
        return 2
    image_path, spec, page_number, output = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
    data = json.load(open(spec, encoding="utf-8"))
    page = next((p for p in data.get("pages", []) if p.get("page_number") == page_number), {})
    image = Image.open(image_path).convert("RGB")
    if page.get("pdf_width"):
        sx, sy = image.width / page["pdf_width"], image.height / page["pdf_height"]
    elif page.get("image_width"):
        sx, sy = image.width / page["image_width"], image.height / page["image_height"]
    else:
        sx = sy = 1.0
    draw = ImageDraw.Draw(image)
    count = 0
    for index, field in enumerate(data.get("form_fields", []), 1):
        if field.get("page_number") != page_number:
            continue
        for key, color in (("label_bounding_box", (40, 90, 220)), ("entry_bounding_box", (220, 30, 30))):
            box = field.get(key)
            if isinstance(box, list) and len(box) == 4:
                scaled = [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
                draw.rectangle(scaled, outline=color, width=2)
                if key == "entry_bounding_box":
                    draw.text((scaled[0] + 2, scaled[1] - 11), str(index), fill=color)
        count += 1
    image.save(output)
    print(f"{count} fields drawn → {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
