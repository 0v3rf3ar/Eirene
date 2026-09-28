"""Slash command completion."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from . import art

WINDOW = 8


class SlashMenu(Static):
    """Command list shown while typing a slash command."""

    DEFAULT_CSS = """
    SlashMenu {
        width: 1fr;
        height: auto;
        margin: 1 0 0 0;
        padding: 0 1;
        border: round $primary;
        background: transparent;
        display: none;
    }
    SlashMenu.showing {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(""))
        self.matches: list[tuple[str, str]] = []
        self.index = 0

    def on_mount(self) -> None:
        self.display = False

    @property
    def open(self) -> bool:
        return bool(self.matches)

    @property
    def choice(self) -> str:
        if not self.matches:
            return ""
        return self.matches[self.index][0]

    def update_for(self, text: str, commands) -> bool:
        """Show matches for a draft; returns whether it is open."""
        prefix = _prefix(text)
        if prefix is None:
            self.close()
            return False
        choices = [c for c in commands if c.name.startswith(prefix)]
        choices.sort(key=lambda command: command.name)
        self.matches = [(c.name, c.summary) for c in choices]
        if not self.matches:
            self.close()
            return False
        self.index = min(self.index, len(self.matches) - 1)
        self.add_class("showing")
        self.display = True
        self._draw()
        # A display:none widget still reports a zero width on its first draw.
        # Redraw after layout so the initial highlight fills the actual row.
        self.call_after_refresh(self._draw)
        return True

    def move(self, delta: int) -> None:
        if not self.matches:
            return
        self.index = (self.index + delta) % len(self.matches)
        self._draw()

    def close(self) -> None:
        self.matches = []
        self.index = 0
        self.remove_class("showing")
        self.display = False

    def _draw(self) -> None:
        body = Text()
        start = max(0, min(self.index - WINDOW // 2, len(self.matches) - WINDOW))
        width = max(len(name) for name, _ in self.matches)
        room = max(self.size.width - 4, 40)
        for position, (name, summary) in enumerate(
                self.matches[start:start + WINDOW], start):
            selected = position == self.index
            marker = art.icon("arrow") if selected else " "
            row = Text()
            row.append(f" {marker} /{name:<{width}}", style="bold" if selected else "")
            row.append(f"  {summary}", style="" if selected else "dim")
            if selected:
                pad = room - row.cell_len
                if pad > 0:
                    row.append(" " * pad)
                row.stylize("reverse")
            body.append_text(row)
            body.append("\n")
        body.remove_suffix("\n")
        self.update(body)


def _prefix(text: str) -> str | None:
    """The partial command name, or None."""
    if not text.startswith("/") or "\n" in text:
        return None
    body = text[1:]
    if " " in body:
        return None
    return body.lower()
