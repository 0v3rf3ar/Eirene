"""Inline list picker."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import NamedTuple

from rich.text import Text
from textual import events
from textual.widgets import Static

from . import art

WINDOW = 10
DETAIL_LINES = 4


class Tab(NamedTuple):
    label: str
    options: list[tuple]
    # (left, right) lines pinned above the rows, aligned the way rows are.
    header: tuple | list = ()


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

    def __init__(self, *, show_detail: bool = True, right_hint: bool = False) -> None:
        super().__init__(Text(""))
        self.show_detail = show_detail
        self.right_hint = right_hint
        self.future: asyncio.Future[str | None] | None = None
        self.options: list[tuple] = []
        self.title = ""
        self.footer = ""
        self.index = 0
        self.filter = ""
        self.on_highlight: Callable[[str], None] | None = None
        self.tabs: list[Tab] = []
        self.tab = 0

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
                     selected: str = "", footer: str = "",
                     tabs: list[tuple] | None = None,
                     tab: int = 0) -> str | None:
        """Show options; returns the value or None.

        With ``tabs`` (see Tab) the options come from the current tab, Tab
        and the arrow keys change it, and ``self.tab`` says where the choice was made.
        """
        self.tabs = [Tab(*item) for item in tabs or []]
        self.tab = tab if 0 <= tab < len(self.tabs) else 0
        if self.tabs:
            options = self.tabs[self.tab].options
        elif not options:
            return None
        self.title = title
        self.footer = footer
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

    def switch_tab(self, delta: int) -> None:
        """Show the next or previous tab, with a fresh filter and highlight."""
        if not self.waiting or not self.tabs:
            return
        self.tab = (self.tab + delta) % len(self.tabs)
        self.options = self.tabs[self.tab].options
        self.index = 0
        self.filter = ""
        self._draw()
        self._preview()

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
        room = max(self.content_size.width, 1)
        if self.tabs:
            body.append_text(self._tab_bar(room))
            body.append("\n\n")
            for left, right in self.tabs[self.tab].header:
                body.append_text(self._header_line(left, right, room))
                body.append("\n")
        if not rows:
            body.append(f"  no match for '{self.filter}'\n" if self.filter else "  nothing here yet\n", style="dim")
        start = max(0, min(self.index - WINDOW // 2, len(rows) - WINDOW))
        for position, row in enumerate(rows[start:start + WINDOW], start):
            label, hint = row[1], row[2]
            selected = position == self.index
            marker = art.icon("arrow") if selected else " "
            option = Text()
            # No bold on the highlighted row: under reverse video many terminals
            # draw it brighter and the highlight splits into two shades.
            option.append(f" {marker} {label}")
            if hint:
                if self.right_hint:
                    tail = Text(str(hint))
                    tail.truncate(max(room - 4, 1), overflow="ellipsis")
                    option.truncate(max(room - tail.cell_len - 1, 1), overflow="ellipsis")
                    option.append(" " * max(room - option.cell_len - tail.cell_len, 1))
                    option.append(tail.plain, style="" if selected else "dim")
                else:
                    option.append(f"  {hint}", style="" if selected else "dim")
            if selected:
                pad = room - option.cell_len
                if pad > 0:
                    option.append(" " * pad)
                option.stylize("reverse")
            body.append_text(option)
            body.append("\n")
        # Keep the menu's height when changing to a shorter tab.
        if self.tabs:
            height = lambda item, shown: len(item.header) + max(min(shown, WINDOW), 1)
            tallest = max(height(item, len(item.options)) for item in self.tabs)
            body.append("\n" * max(tallest - height(self.tabs[self.tab], len(rows)), 0))
        detail = self._detail(rows)
        if self.footer:
            footer = Text(" " + self.footer, style="dim")
            if detail and self.show_detail:
                footer.append(" · " + " ".join(detail.split()), style="dim italic")
            footer.truncate(room, overflow="ellipsis")
            body.append_text(footer)
            body.append("\n")
        elif self.show_detail:
            width = max(self.size.width - 6, 30)
            lines = _wrap(detail, width) if detail else []
            # Reserve room for the longest detail so the menu keeps its height
            # while the highlight moves.
            every = [row for item in self.tabs for row in item.options] or self.options
            reserved = max((len(_wrap(row[3], width)) for row in every
                            if len(row) > 3 and row[3]), default=0)
            for line in lines + [""] * (reserved - len(lines)):
                body.append(f"   {line}\n", style="dim italic")
        if self.filter:
            body.append(f"  Filter: {self.filter}\n", style="dim")
        body.remove_suffix("\n")
        self.update(body)

    def _header_line(self, left: str, right: str, room: int) -> Text:
        """A non-selectable line, in the same columns as the rows below it."""
        line = Text(f"   {left}", style="dim" if right else "")
        if right:
            tail = Text(right, style="dim")
            tail.truncate(max(room - 4, 1), overflow="ellipsis")
            line.truncate(max(room - tail.cell_len - 1, 1), overflow="ellipsis")
            line.append(" " * max(room - line.cell_len - tail.cell_len, 1))
            line.append_text(tail)
        else:
            line.truncate(room, overflow="ellipsis")
        return line

    def _tab_bar(self, room: int) -> Text:
        bar = Text(" ")
        for position, item in enumerate(self.tabs):
            label = item.label
            bar.append(f" {label} ", style="reverse" if position == self.tab else "dim")
            bar.append(" ")
        hint = "tab to switch"
        if bar.cell_len + len(hint) < room:
            bar.append(" " * (room - bar.cell_len - len(hint)))
            bar.append(hint, style="dim")
        return bar

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
        if self.tabs and key in ("tab", "right", "shift+tab", "backtab", "left"):
            self.switch_tab(1 if key in ("tab", "right") else -1)
            return
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
