"""Inline approval prompt."""

from __future__ import annotations

import asyncio

from rich.text import Text
from textual import events
from textual.widgets import Static

from ..core.agent import ALWAYS, NO, YES
from . import art

CHOICES = [(YES, "yes"), (ALWAYS, "yes, and don't ask again for this tool"),
           (NO, "no, stop here")]


class PermissionBar(Static):
    """Asks the user to approve one tool call."""

    DEFAULT_CSS = """
    PermissionBar {
        width: 1fr;
        height: auto;
        padding: 0 1;
        background: transparent;
        display: none;
    }
    PermissionBar.showing {
        display: block;
    }
    """

    can_focus = True

    def __init__(self) -> None:
        super().__init__(Text(""))
        self.future: asyncio.Future[str] | None = None
        self.index = 0
        self.title = ""
        self.reason = ""

    def on_mount(self) -> None:
        self.display = False

    def on_resize(self, event: events.Resize) -> None:
        if self.waiting:
            self._draw()

    @property
    def waiting(self) -> bool:
        return self.future is not None and not self.future.done()

    def cancel(self) -> None:
        """Dismiss as a denial."""
        self._resolve(NO)

    async def ask(self, title: str, reason: str) -> str:
        """Show the prompt and wait for a choice."""
        self.title = title
        self.reason = reason
        self.index = 0
        self.future = asyncio.get_running_loop().create_future()
        self.add_class("showing")
        self.display = True
        self._draw()
        self.call_after_refresh(self._draw)
        self.focus()
        try:
            return await self.future
        finally:
            self.remove_class("showing")
            self.display = False
            self.future = None

    def _resolve(self, answer: str) -> None:
        if self.future and not self.future.done():
            self.future.set_result(answer)

    def _draw(self) -> None:
        body = Text()
        body.append(f"{art.icon('warn')} {self.title}\n", style="bold")
        if self.reason:
            body.append(f"  {self.reason}\n", style="dim")
        room = max(self.size.width - 4, 1)
        for position, (_, label) in enumerate(CHOICES):
            selected = position == self.index
            marker = art.icon("arrow") if selected else " "
            row = Text(f" {marker} {position + 1}. {label}",
                       style="bold" if selected else "dim")
            if selected:
                pad = room - row.cell_len
                if pad > 0:
                    row.append(" " * pad)
                row.stylize("reverse")
            body.append_text(row)
            body.append("\n")
        body.append("  ↑↓ move · enter choose · y / a / n · esc to deny", style="dim")
        self.update(body)

    async def _on_key(self, event: events.Key) -> None:
        if self.future is None:
            return
        key = event.key
        event.stop()
        event.prevent_default()
        if key in ("up", "k"):
            self.index = (self.index - 1) % len(CHOICES)
            self._draw()
        elif key in ("down", "j"):
            self.index = (self.index + 1) % len(CHOICES)
            self._draw()
        elif key == "enter":
            self._resolve(CHOICES[self.index][0])
        elif key in ("y", "1"):
            self._resolve(YES)
        elif key in ("a", "2"):
            self._resolve(ALWAYS)
        elif key in ("n", "3", "escape"):
            self._resolve(NO)
