"""Optional December snowfall, independent of conversation content."""

from __future__ import annotations

import math
import random
from datetime import date
from time import monotonic
from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from .chat import Transcript

# One switch to retire the decoration in a future release.
SNOW_ENABLED = True
SNOW_INTERVAL = 1 / 60
DOT_BITS = ((0x01, 0x08), (0x02, 0x10), (0x04, 0x20), (0x40, 0x80))


def in_snow_season(today: date | None = None) -> bool:
    """Snow automatically for one calendar month around Christmas."""
    return (today or date.today()).month == 12


class Snowfall:
    """Sparse dots, with a silent session override for the hidden command."""

    def __init__(self, transcript: Transcript) -> None:
        self.transcript = transcript
        self.override: bool | None = None
        self._timer = None
        self._calendar_timer = None
        self._last_enabled = False
        self._ascii = False
        self._started = monotonic()
        self._flakes = [
            (random.random(), random.random(), random.uniform(1.0, 2.0),
             random.uniform(0, math.tau))
            for _ in range(45)
        ]

    @property
    def enabled(self) -> bool:
        if not SNOW_ENABLED:
            return False
        if self.override is not None:
            return self.override
        config = getattr(self.transcript.app, "config", {})
        return bool(config.get("seasonal_effects", True)) and in_snow_season()

    def mount(self) -> None:
        self._calendar_timer = self.transcript.set_interval(60, self._check_calendar)
        self.transcript.refresh_snow()

    def _check_calendar(self) -> None:
        enabled = self.enabled
        if enabled != self._last_enabled:
            self._last_enabled = enabled
            self.transcript.refresh_snow()

    def toggle(self) -> None:
        self.override = not self.enabled
        self.transcript.refresh_snow()

    def start(self) -> None:
        self.stop()
        self._last_enabled = self.enabled
        config = getattr(self.transcript.app, "config", {})
        self._ascii = bool(config.get("accessible_icons", False))
        if not self.enabled or config.get("reduce_motion", False):
            return
        self._started = monotonic()
        self._timer = self.transcript.set_interval(SNOW_INTERVAL, self.transcript.refresh)
        self.transcript.refresh()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self.transcript.refresh()

    def close(self) -> None:
        self.stop()
        if self._calendar_timer is not None:
            self._calendar_timer.stop()
            self._calendar_timer = None

    def render(self) -> Text | None:
        if self._timer is None:
            return None
        width, height = self.transcript.content_size
        top = max((child.virtual_region.bottom + child.styles.margin.bottom
                   for child in self.transcript.children if child.display), default=0)
        available = height - top
        if width < 1 or available < 1:
            return Text("")
        rows = [[0] * width for _ in range(height)]
        elapsed = monotonic() - self._started
        count = min(len(self._flakes), max(1, width * available // 100))
        for x, y, speed, phase in self._flakes[:count]:
            dot_x = math.floor((x * width + 0.6 * math.sin(elapsed * 0.35 + phase)) * 2)
            dot_x %= width * 2
            # Stagger entry above the viewport before recycling at the bottom.
            dot_y = math.floor((elapsed * speed - y * available) * 4)
            if dot_y < 0:
                continue
            dot_y %= available * 4
            column, subcolumn = divmod(dot_x, 2)
            row, subrow = divmod(dot_y, 4)
            rows[top + row][column] |= DOT_BITS[subrow][subcolumn]
        return Text("\n".join("".join(("." if self._ascii else chr(0x2800 + dots))
                                      if dots else " " for dots in row)
                              for row in rows),
                    style="dim", no_wrap=True, overflow="crop")
