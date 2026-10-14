"""Draw an RGBA Kitty image without painting a rectangular text background."""

from __future__ import annotations

import base64
import io
import secrets

from textual.widget import Widget
from textual.geometry import Region


def graphics_command(**values) -> str:
    payload = values.pop("payload", None)
    header = ",".join(f"{key}={value}" for key, value in values.items())
    return f"\x1b_G{header}" + (f";{payload}" if payload else "") + "\x1b\\"


class KittyPortrait(Widget):
    """An invisible layout anchor with a native graphics placement above text."""

    TRANSPARENT_OVERLAY = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self._image = None
        self._image_id = secrets.randbelow(2**31 - 1) + 1
        self._uploaded = False
        self._placed = False
        self._placement_region = Region()

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, value):
        self._image = value
        self._uploaded = False
        self.refresh(layout=True)

    def place_above_input(self, border_y: int):
        if self._image is None:
            return
        from textual_image._terminal import get_cell_size
        cell = get_cell_size()
        width = round(6 * cell.height / cell.width * self._image.width / self._image.height)
        self._placement_region = Region(max(0, self.app.size.width - width - 1),
                                        max(0, border_y - 6), width, 6)

    def _write(self, sequence: str):
        driver = self.app._driver
        if driver is None or self.app.is_headless:
            return
        from textual_image import _terminal
        wrap = getattr(_terminal, "prepare_terminal_sequence", lambda value: value)
        driver.write(wrap(sequence))
        driver.flush()

    def paint(self):
        if not self.parent.display:
            self.clear()
            return
        if self._image is None or not self._placement_region.width:
            return
        if not self._uploaded:
            data = io.BytesIO()
            self._image.save(data, format="PNG")
            encoded = base64.b64encode(data.getvalue()).decode("ascii")
            commands = []
            for start in range(0, len(encoded), 4096):
                chunk = encoded[start:start + 4096]
                commands.append(graphics_command(a="t", f=100, i=self._image_id,
                    m=int(start + 4096 < len(encoded)), q=2, payload=chunk))
            self._write("".join(commands))
            self._uploaded = True
        # Refresh only our placement after Textual repaints. Cursor save/restore
        # and C=1 leave the input cursor and text beneath the image untouched.
        region = self._placement_region
        sequence = graphics_command(a="d", d="i", i=self._image_id, p=1, q=2)
        sequence += f"\x1b7\x1b[{region.y + 1};{region.x + 1}H"
        sequence += graphics_command(a="p", i=self._image_id, p=1,
            c=region.width, r=region.height, z=1, C=1, q=2)
        sequence += "\x1b8"
        self._write(sequence)
        self._placed = True

    def clear(self):
        if self._placed or self._uploaded:
            self._write(graphics_command(a="d", d="I", i=self._image_id, q=2))
        self._placed = self._uploaded = False

    def on_unmount(self):
        self.clear()
