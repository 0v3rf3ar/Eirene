"""Live status line above the composer."""

from __future__ import annotations

import time
from datetime import datetime

from rich.text import Text
from rich.style import Style
from textual.color import Color
from textual.widgets import Static

from . import art
from .format import strip_escapes
from ..core.usage import human_count

TICK = 0.1
FADE_AFTER = (5, 15, 30, 60)
BRIGHTNESS = (1.0, 0.8, 0.6, 0.45, 0.3)
CONNECTION_PHASES = {"reconnecting", "waiting for response"}
PROVIDER_PHASES = {"thinking", "reasoning", "answering", "working"}


class ContextIndicator(Static):
    """Show high context usage on the right, directly above the input."""

    DEFAULT_CSS = """
    ContextIndicator {
        width: 1fr;
        height: 1;
        padding: 0 1;
        text-align: right;
        color: $warning;
        background: transparent;
        display: none;
    }
    """

    def on_mount(self):
        self.set_interval(0.25, self.refresh_context)
        self.refresh_context()

    def refresh_context(self):
        agent = self.app.agent
        used, limit = agent.context_usage() if agent.ready else (0, 0)
        self.display = bool(limit > 0 and used / limit > 0.85)
        self.update(Text(f"context ~{used / limit:.0%} · {human_count(used)} / {human_count(limit)}"
                         if self.display else "", no_wrap=True, overflow="ellipsis"))


# What the agent is doing, in one of five words.
ACTIVITY = {"reasoning": "reasoning", "answering": "answering",
            "writing": "coding", "running": "coding"}
TOOL_ACTIVITY = {"write": "coding", "exec": "coding", "read": "searching"}


def elapsed_label(seconds: float) -> str:
    """3s, 1m 3s, 1h 2m 1s."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m {seconds}s"


def clock_label(moment: datetime) -> str:
    """7:38 PM; built by hand because %-I is not portable to Windows."""
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


class StatusLine(Static):
    """A spinner, its word, the elapsed time and what the agent is doing."""

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
        self.input_tokens = 0
        self.output_tokens = 0
        self.verb = art.verb()
        self._spinner_style = art.spinner_style()
        self.note = ""
        self.note_icon = "dot"
        self._tick = 0
        self._timer = None
        self._last_activity = 0.0
        self._connection_wait = False
        self._active_tools: set[str] = set()
        self._writing_tools: set[str] = set()
        self._tool_kinds: dict[str, str] = {}

    def on_mount(self) -> None:
        self._timer = self.set_interval(TICK, self._refresh)

    def start(self, spinner: int | None = None) -> None:
        """Begin a turn; pass the session's spinner to keep it for the whole session."""
        self.active = True
        self.started = time.monotonic()
        self._last_activity = self.started
        self._connection_wait = False
        self._active_tools.clear()
        self._writing_tools.clear()
        self._tool_kinds.clear()
        self.input_tokens = 0
        self.output_tokens = 0
        self.phase = "thinking"
        self.note = ""
        self.verb = art.verb()
        self._spinner_style = art.spinner_style() if spinner is None else spinner
        self._refresh()

    def stop(self, note: str = "", icon: str = "dot") -> None:
        self.active = False
        self.phase = ""
        self._connection_wait = False
        self._active_tools.clear()
        self._writing_tools.clear()
        self._tool_kinds.clear()
        self.note = note
        self.note_icon = icon
        self._refresh()

    def set_phase(self, phase: str) -> None:
        if phase in CONNECTION_PHASES:
            self.set_connection_wait()
            return
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

    def start_tool(self, tool_id: str, kind: str = "") -> None:
        self._active_tools.add(tool_id)
        self._tool_kinds[tool_id] = kind
        if kind == "write":
            self._writing_tools.add(tool_id)
        self.mark_activity()

    def finish_tool(self, tool_id: str) -> None:
        self._active_tools.discard(tool_id)
        self._writing_tools.discard(tool_id)
        self._tool_kinds.pop(tool_id, None)
        self.mark_activity()

    @property
    def activity(self) -> str:
        """thinking, reasoning, coding, searching or answering; tools win over the phase."""
        kinds = set(self._tool_kinds.values())
        for kind in ("write", "exec", "read"):
            if kind in kinds:
                return TOOL_ACTIVITY[kind]
        if self._active_tools:
            return "thinking"
        return ACTIVITY.get(self.phase, "thinking")

    @property
    def spinner_style(self) -> int:
        """Which spinner this turn uses, so the window title can match it."""
        return self._spinner_style

    @property
    def writing_files(self) -> bool:
        return bool(self._writing_tools)

    @property
    def running_tools(self) -> bool:
        return bool(self._active_tools)

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
                body.append(f"  {art.icon(self.note_icon)} {self.note}", style="dim")
            self.update(body)
            return

        if self.phase == "idle":
            self.update(Text("  • idle · waiting for background commands  esc to stop", style="dim"))
            return

        # spinner, word, then "(1m 3s · thinking)"; token counts stay out of the way.
        body = Text()
        config = getattr(self.app, "config", None) if self.is_mounted else None
        frame = "*" if config and config.get("reduce_motion", False) else art.spinner_frame(self._tick, self._spinner_style)
        working_style = self._working_style(self.shade_level)
        body.append(f"  {frame} ", style=working_style)
        body.append(f"{self.verb}…", style=working_style)
        elapsed = elapsed_label(time.monotonic() - self.started)
        body.append(f" ({elapsed} {art.icon('dot')} {self.activity})", style="dim")
        self.update(body)
