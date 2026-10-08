"""Live status line above the composer."""

from __future__ import annotations

import time

from rich.text import Text
from rich.style import Style
from textual.color import Color
from textual.widgets import Static

from . import art
from .format import strip_escapes

TICK = 0.1
FADE_AFTER = (5, 15, 30, 60)
BRIGHTNESS = (1.0, 0.8, 0.6, 0.45, 0.3)
CONNECTION_PHASES = {"reconnecting", "waiting for response"}
PROVIDER_PHASES = {"thinking", "reasoning", "answering", "working"}


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
        self._last_activity = 0.0
        self._connection_wait = False
        self._active_tools: set[str] = set()

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK, self._refresh)

    def start(self) -> None:
        self.active = True
        self.started = time.monotonic()
        self._last_activity = self.started
        self._connection_wait = False
        self._active_tools.clear()
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
        self._connection_wait = False
        self._active_tools.clear()
        self.note = note
        self._refresh()

    def set_phase(self, phase: str) -> None:
        if phase in CONNECTION_PHASES:
            self.set_connection_wait()
            return
        if phase not in {"thinking", "reasoning"} and not self.thinking and self.started:
            self.thinking = time.monotonic() - self.started
        self.phase = " ".join(strip_escapes(phase).split())[:240]
        self.mark_activity()

    def mark_activity(self) -> None:
        """Actual response/tool activity restores the animation immediately."""
        self._last_activity = time.monotonic()
        self._connection_wait = False
        self._refresh()

    def set_connection_wait(self) -> None:
        """Retry notices change shade, without replacing the working label."""
        self._connection_wait = True
        self._refresh()

    def start_tool(self, tool_id: str) -> None:
        self._active_tools.add(tool_id)
        self.mark_activity()

    def finish_tool(self, tool_id: str) -> None:
        self._active_tools.discard(tool_id)
        self.mark_activity()

    @property
    def shade_level(self) -> int:
        if not self.active or self._active_tools or (not self._connection_wait and self.phase not in PROVIDER_PHASES):
            return 0
        idle = max(0.0, time.monotonic() - self._last_activity)
        level = sum(idle >= threshold for threshold in FADE_AFTER)
        return max(1, level) if self._connection_wait else level

    def _working_style(self, level: int) -> Style:
        foreground, background = Color(255, 255, 255), Color(0, 0, 0)
        if self.is_mounted:
            theme = self.app.current_theme
            terminal = self.app.ansi_theme_dark if theme.dark else self.app.ansi_theme_light
            foreground = Color.parse(theme.primary or theme.foreground or "ansi_default")
            background = Color.parse(theme.background or "ansi_default")
            if foreground.ansi == -1:
                foreground = Color(*terminal.foreground_color)
            if background.ansi == -1:
                background = Color(*terminal.background_color)
        colour = background.blend(foreground, BRIGHTNESS[level])
        return Style(color=colour.hex, bold=level == 0)

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
        working_style = self._working_style(self.shade_level)
        body.append(f"  {frame} ", style=working_style)
        body.append(f"{self.verb}… ", style=working_style)
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
