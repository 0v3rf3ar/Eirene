"""Inline list picker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from rich.text import Text
from textual import events
from textual.widgets import Static

from . import art

WINDOW = 10
DETAIL_LINES = 4


def _wrap(text: str, width: int) -> list[str]:
    """Fold a description onto a few lines."""
    import textwrap
    lines = textwrap.wrap(" ".join(str(text).split()), width=max(width, 20))
    if len(lines) > DETAIL_LINES:
        lines = lines[:DETAIL_LINES]
        lines[-1] = lines[-1][:width - 1] + "…"
    return lines


class Picker(Static):
    """Scrollable single-choice list."""

    DEFAULT_CSS = """
    Picker {
        width: 1fr;
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        border: round $primary;
        background: transparent;
        display: none;
    }
    Picker.showing {
        display: block;
    }
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__(Text(""))
        self.future: asyncio.Future[str | None] | None = None
        self.options: list[tuple] = []
        self.title = ""
        self.index = 0
        self.filter = ""
        self.on_highlight: Callable[[str], None] | None = None

    def on_mount(self) -> None:
        self.display = False

    def on_resize(self, event: events.Resize) -> None:
        """Rewrap the description for the new width."""
        if self.waiting:
            self._draw()

    @property
    def waiting(self) -> bool:
        return self.future is not None and not self.future.done()

    def cancel(self) -> None:
        """Dismiss without a choice."""
        self._resolve(None)

    async def choose(self, title: str, options: list[tuple], *,
                     on_highlight: Callable[[str], None] | None = None,
                     selected: str = "") -> str | None:
        """Show options; returns the value or None."""
        if not options:
            return None
        self.title = title
        self.options = options
        self.index = next((row for row, option in enumerate(options)
                           if str(option[0]) == selected), 0)
        self.filter = ""
        self.on_highlight = on_highlight
        self.future = asyncio.get_running_loop().create_future()
        self.add_class("showing")
        self.display = True
        self._draw()
        # The widget has no width while display:none; redraw once layout gives
        # it a real row width so the initial selection reaches the edge.
        self.call_after_refresh(self._draw)
        self._preview()
        self.focus()
        try:
            return await self.future
        finally:
            self.remove_class("showing")
            self.display = False
            self.future = None
            self.on_highlight = None

    def _visible(self) -> list[tuple]:
        if not self.filter:
            return self.options
        needle = self.filter.lower()
        return [row for row in self.options
                if needle in row[1].lower() or needle in row[0].lower()]

    def _resolve(self, value: str | None) -> None:
        if self.future and not self.future.done():
            self.future.set_result(value)

    def _preview(self) -> None:
        rows = self._visible()
        if self.on_highlight and rows and 0 <= self.index < len(rows):
            self.on_highlight(str(rows[self.index][0]))

    def _move(self, delta: int) -> None:
        rows = self._visible()
        if not self.waiting or not rows:
            return
        self.index = (self.index + delta) % len(rows)
        self._draw()
        self._preview()

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        event.stop()
        self._move(-1)

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        event.stop()
        self._move(1)

    def _draw(self) -> None:
        rows = self._visible()
        body = Text()
        body.append(f"{art.icon('info')} {self.title}\n", style="bold")
        if not rows:
            body.append(f"  no match for '{self.filter}'\n", style="dim")
        start = max(0, min(self.index - WINDOW // 2, len(rows) - WINDOW))
        room = max(self.size.width - 4, 1)
        for position, row in enumerate(rows[start:start + WINDOW], start):
            label, hint = row[1], row[2]
            selected = position == self.index
            marker = art.icon("arrow") if selected else " "
            option = Text()
            option.append(f" {marker} {label}", style="bold" if selected else "")
            if hint:
                option.append(f"  {hint}", style="" if selected else "dim")
            if selected:
                pad = room - option.cell_len
                if pad > 0:
                    option.append(" " * pad)
                option.stylize("reverse")
            body.append_text(option)
            body.append("\n")
        detail = self._detail(rows)
        if detail:
            for line in _wrap(detail, max(self.size.width - 6, 30)):
                body.append(f"   {line}\n", style="dim italic")
        if self.filter:
            body.append(f"  Filter: {self.filter}\n", style="dim")
        body.remove_suffix("\n")
        self.update(body)

    def _detail(self, rows: list[tuple]) -> str:
        """The long text for whatever is highlighted."""
        if not rows or not 0 <= self.index < len(rows):
            return ""
        row = rows[self.index]
        return str(row[3]) if len(row) > 3 else ""

    async def _on_key(self, event: events.Key) -> None:
        if self.future is None:
            return
        rows = self._visible()
        key = event.key
        event.stop()
        event.prevent_default()
        if key == "up":
            self._move(-1)
            return
        elif key == "down":
            self._move(1)
            return
        elif key == "enter":
            if rows and 0 <= self.index < len(rows):
                self._resolve(rows[self.index][0])
            return
        elif key == "escape":
            self._resolve(None)
            return
        elif key == "backspace":
            self.filter = self.filter[:-1]
            self.index = 0
        elif event.is_printable and event.character:
            self.filter += event.character
            self.index = 0
        self._draw()
        self._preview()
