"""The chooser behind a bare --resume."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from . import art
from .picker import Picker
from .theme import PLAIN


def when(stamp: float) -> str:
    """Short, human date for a session."""
    now = time.time()
    if now - stamp < 86400:
        return time.strftime("%H:%M today", time.localtime(stamp))
    if now - stamp < 172800:
        return time.strftime("%H:%M yesterday", time.localtime(stamp))
    return time.strftime("%d %b %H:%M", time.localtime(stamp))


def options(rows: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Turn session records into neatly aligned picker rows."""
    names = [str(info.get("name") or "untitled") for info in rows]
    # Keep every metadata field in a stable column without letting one very
    # long generated title push useful information off most terminals.
    name_width = min(max((cell_len(name) for name in names), default=0), 36)
    out = []
    for info, name in zip(rows, names):
        turns = int(info.get("turns") or 0)
        short_id = str(info["id"])[:8]
        used = when(float(info["mtime"]))
        label = set_cell_size(name, name_width)
        hint = f"{used:<15}  {short_id:<8}  {turns:>3} turns"
        out.append((str(info["id"]), label, hint))
    return out


class Header(Static):
    """One line above the list."""

    DEFAULT_CSS = """
    Header {
        width: 1fr;
        height: auto;
        padding: 1 1 0 1;
        background: transparent;
    }
    """


class Chooser(App):
    """Pick a saved session to continue."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "eirene"

    CSS = """
    Screen {
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "quit", "leave", priority=True, show=False),
    ]

    def __init__(self, rows: list[dict[str, Any]], sandbox: Path):
        super().__init__()
        self.rows = rows
        self.sandbox = sandbox
        self.chosen = ""

    def compose(self) -> ComposeResult:
        body = Text()
        body.append(f"{art.icon('dir')} {self.sandbox}\n", style="bold")
        body.append(f"{len(self.rows)} saved sessions here", style="dim")
        yield Header(body)
        yield Picker()

    def on_mount(self) -> None:
        self.register_theme(PLAIN)
        self.theme = "eirene"
        self.run_worker(self._ask(), exclusive=True)

    async def _ask(self) -> None:
        picker = self.query_one(Picker)
        self.chosen = await picker.choose("continue which session?",
                                          options(self.rows)) or ""
        self.exit()


def choose_session(rows: list[dict[str, Any]], sandbox: Path) -> str:
    """Show the list; returns the chosen id or empty."""
    app = Chooser(rows, sandbox)
    app.run()
    return app.chosen
