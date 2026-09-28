"""A responsive session-restoration overlay."""
from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
import struct
import time
import zlib

from rich.style import Style
from rich.text import Text
from textual import events
from textual.widgets import Static

from .progress import progress_bar

SPLASH_SECONDS = 1.0


@lru_cache(maxsize=1)
def _logo() -> tuple[int, int, bytes]:
    data = zlib.decompress(files("eirene.ui").joinpath("logo.gray.zlib").read_bytes())
    width, height = struct.unpack(">HH", data[:4])
    return width, height, data[4:]


@lru_cache(maxsize=256)
def _gray(value: int) -> str:
    return f"#{value:02x}{value:02x}{value:02x}"


def pixel_logo(width: int, height: int) -> Text:
    """Fit the logo while accounting for two pixels per terminal cell."""
    source_width, source_height, pixels = _logo()
    columns = max(1, min(width, height * 2))
    rows = max(1, min(height, (columns + 1) // 2))
    body = Text(no_wrap=True, overflow="crop")
    for y in range(rows):
        if y:
            body.append("\n")
        top_row = min(source_height - 1, (y * 2) * source_height // (rows * 2))
        bottom_row = min(source_height - 1, (y * 2 + 1) * source_height // (rows * 2))
        for x in range(columns):
            source_x = min(source_width - 1, x * source_width // columns)
            top = pixels[top_row * source_width + source_x]
            bottom = pixels[bottom_row * source_width + source_x]
            body.append("▀", style=Style(color=_gray(top), bgcolor=_gray(bottom)))
    return body


class StartupSplash(Static):
    """An overlay that leaves startup work and input responsive underneath."""

    DEFAULT_CSS = """
    StartupSplash {
        layer: splash;
        position: absolute;
        width: 100vw;
        height: 100vh;
        overlay: screen;
        background: #000000;
        color: #ffffff;
        content-align: center top;
        display: none;
    }
    """
    can_focus = False

    def __init__(self):
        super().__init__(Text(""))
        self.progress = 0.0
        self._started = 0.0
        self._timer = None
        self._finish_timer = None
        self._logo_size = None
        self._pixels = Text("")

    def start(self) -> None:
        self._stop_timers()
        if SPLASH_SECONDS <= 0:
            return
        self.progress = 0.0
        self._started = time.monotonic()
        self.display = True
        self._draw()
        self._timer = self.set_interval(1 / 30, self._advance)

    def _advance(self) -> None:
        elapsed = time.monotonic() - self._started
        self.progress = min(0.95, elapsed / SPLASH_SECONDS)
        self._draw()

    def finish(self) -> None:
        """Reveal the restored session after at least one second of loading."""
        if not self.display:
            return
        remaining = max(0.0, SPLASH_SECONDS - (time.monotonic() - self._started))
        if self._finish_timer is not None:
            self._finish_timer.stop()
        if remaining:
            self._finish_timer = self.set_timer(remaining, self._complete)
        else:
            self._complete()

    def _complete(self) -> None:
        self._stop_timers()
        self.progress = 1.0
        self._draw()
        # Show the completed bar for a frame before revealing history.
        self._finish_timer = self.set_timer(1 / 30, self._hide)

    def _hide(self) -> None:
        self._finish_timer = None
        self.display = False

    def _stop_timers(self) -> None:
        for timer in (self._timer, self._finish_timer):
            if timer is not None:
                timer.stop()
        self._timer = self._finish_timer = None

    def on_unmount(self) -> None:
        self._stop_timers()

    def on_resize(self, event: events.Resize) -> None:
        if self.display:
            self._draw()

    def _draw(self) -> None:
        width, height = max(1, self.app.size.width), max(1, self.app.size.height)
        image_size = (max(1, width - 4), max(1, height - 6))
        if self._logo_size != image_size:
            self._pixels = pixel_logo(*image_size)
            self._logo_size = image_size
        body = Text(no_wrap=True, overflow="crop")
        picture = self._pixels if height >= 4 else Text("")
        picture_rows = picture.split("\n") if picture.plain else []
        top = max(0, (height - len(picture_rows)) // 2)
        footer_rows = min(2, height)
        for y in range(height - footer_rows):
            row_index = y - top
            if 0 <= row_index < len(picture_rows):
                row = picture_rows[row_index]
                left = max(0, (width - row.cell_len) // 2)
                body.append(" " * left)
                body.append(row)
                body.append(" " * max(0, width - left - row.cell_len))
            else:
                body.append(" " * width)
            body.append("\n")
        if height >= 2:
            label = f"loading session {int(self.progress * 100)}%"[:width]
            left = (width - len(label)) // 2
            body.append(" " * left)
            body.append(label, style="#b8bec9")
            body.append(" " * (width - left - len(label)) + "\n")
        body.append(progress_bar(self.progress, width))
        body.justify = "left"
        self.update(body)
