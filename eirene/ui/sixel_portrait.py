"""Transparent Sixel portraits drawn in the same update as terminal text."""

from __future__ import annotations

from itertools import groupby

from textual._compositor import CompositorUpdate
from textual.geometry import Region
from textual.widget import Widget


def transparent_sixels(image) -> str:
    """Encode only visible pixels; P2=1 leaves the terminal background intact."""
    rgba = image.convert("RGBA")
    indexed = rgba.convert("RGB").quantize(colors=256)
    pixels = indexed.tobytes()
    alpha = rgba.getchannel("A").tobytes()
    palette = indexed.getpalette()
    width, height = rgba.size
    colors = sorted({color for color, opacity in zip(pixels, alpha) if opacity >= 128})
    commands = [f'\x1bP0;1;0q"1;1;{width};{height}']
    for color in colors:
        rgb = palette[color * 3:color * 3 + 3]
        commands.append(f"#{color};2;" + ";".join(str(round(v * 100 / 255)) for v in rgb))
    for top in range(0, height, 6):
        bands = {}
        for row in range(top, min(top + 6, height)):
            for x in range(width):
                offset = row * width + x
                if alpha[offset] >= 128:
                    band = bands.setdefault(pixels[offset], bytearray(width))
                    band[x] |= 1 << (row - top)
        for color, band in bands.items():
            commands.append(f"#{color}")
            # Zero bits advance across transparent padding without painting it.
            for value, run in groupby(bytes(band).rstrip(b"\0")):
                count = sum(1 for _ in run)
                char = chr(63 + value)
                commands.append(f"!{count}{char}" if count >= 4 else char * count)
            commands.append("$")
        if top + 6 < height:
            commands.append("-")
    commands.append("\x1b\\")
    return "".join(commands)


class PortraitUpdate(CompositorUpdate):
    """Keep text erasure and the replacement picture inside Textual's sync."""

    def __init__(self, update, portrait):
        self.update = update
        self.portrait = portrait

    def render_segments(self, console):
        text = self.update.render_segments(console)
        portrait = self.portrait
        if portrait.parent.display and portrait.image is not None:
            portrait.place_above_input(portrait.app.query("Composer Rule").first().region.y)
        region = portrait._placement_region
        spans = getattr(self.update, "spans", None)
        if (portrait._placed and portrait._encoded is not None and spans is not None
                and not any(region.y <= y < region.bottom and x1 < region.right and x2 > region.x
                            for y, x1, x2 in spans)):
            # Typing below the picture does not erase it. Leave its pixels alone.
            return text
        return text + portrait.terminal_sequence()


class SixelPortrait(Widget):
    TRANSPARENT_OVERLAY = True

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.visible = False
        self._image = None
        self._placement_region = Region()
        self._encoded = None
        self._placed = False

    @property
    def image(self):
        return self._image

    @image.setter
    def image(self, value):
        self._image = value
        self._encoded = None
        # Repaint the underlying text to remove pixels from the previous pose.
        # Never unmount/recreate a widget between the two eye poses.
        self.screen.refresh()

    def place_above_input(self, border_y):
        if self._image is None:
            return
        from textual_image._terminal import get_cell_size
        cell = get_cell_size()
        width = max(1, round(6 * cell.height / cell.width * self._image.width / self._image.height))
        region = Region(max(0, self.app.size.width - width - 1), max(0, border_y - 6), width, 6)
        if region != self._placement_region:
            self._placement_region = region
            self._placed = False
            self.screen.refresh()

    def paint(self):
        # Rendering happens in PortraitUpdate, before Textual ends its sync.
        pass

    def terminal_sequence(self):
        if not self.parent.display or self._image is None:
            return ""
        self.place_above_input(self.app.query("Composer Rule").first().region.y)
        from PIL import Image
        from textual_image._terminal import get_cell_size
        cell = get_cell_size()
        region = self._placement_region
        size = (region.width * cell.width, region.height * cell.height)
        if self._encoded is None or self._encoded[0] != size:
            self._encoded = (size, transparent_sixels(self._image.resize(size, Image.Resampling.NEAREST)))
        self._placed = True
        sequence = f"\x1b7\x1b[{region.y + 1};{region.x + 1}H" + self._encoded[1] + "\x1b8"
        from textual_image import _terminal
        return getattr(_terminal, "prepare_terminal_sequence", lambda value: value)(sequence)

    def clear(self):
        if self._placed:
            self._placed = False
            self.screen.refresh()
