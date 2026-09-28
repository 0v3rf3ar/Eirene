"""Live status line above the composer."""

from __future__ import annotations

import time

from rich.text import Text
from textual.widgets import Static

from . import art
from .format import strip_escapes

TICK = 0.1


class StatusLine(Static):
    """Spinner, elapsed time and token counts."""

    DEFAULT_CSS = """
    StatusLine {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(""))
        self.active = False
        self.phase = ""
        self.started = 0.0
        self.thinking = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.verb = art.verb()
        self._spinner_style = art.spinner_style()
        self.note = ""
        self._tick = 0
        self._timer = None

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK, self._refresh)

    def start(self) -> None:
        self.active = True
        self.started = time.monotonic()
        self.thinking = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.phase = "thinking"
        self.note = ""
        self.verb = art.verb()
        self._spinner_style = art.spinner_style()
        self._refresh()

    def stop(self, note: str = "") -> None:
        self.active = False
        self.phase = ""
        self.note = note
        self._refresh()

    def set_phase(self, phase: str) -> None:
        if phase not in {"thinking", "reasoning"} and not self.thinking and self.started:
            self.thinking = time.monotonic() - self.started
        self.phase = " ".join(strip_escapes(phase).split())[:240]
        self._refresh()

    def set_tokens(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens

    def _refresh(self) -> None:
        self._tick += 1
        if not self.active:
            body = Text()
            if self.note:
                body.append(f"  {art.icon('dot')} {self.note}", style="dim")
            self.update(body)
            return

        elapsed = time.monotonic() - self.started
        body = Text()
        config = getattr(self.app, "config", None) if self.is_mounted else None
        frame = "*" if config and config.get("reduce_motion", False) else art.spinner_frame(self._tick, self._spinner_style)
        body.append(f"  {frame} ", style="bold")
        body.append(f"{self.verb}… ", style="bold")
        if self.phase:
            body.append(f"{self.phase} ", style="dim")
        body.append(f"({elapsed:.0f}s", style="dim")
        if self.output_tokens:
            body.append(f" {art.icon('dot')} {art.icon('tokens')} "
                        f"{self.output_tokens} tokens", style="dim")
        if self.thinking:
            body.append(f" {art.icon('dot')} thought for {self.thinking:.0f}s",
                        style="dim")
        body.append(")", style="dim")
        body.append("  esc to stop", style="dim")
        self.update(body)
