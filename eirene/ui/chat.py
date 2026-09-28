"""Transcript widgets."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Static

from . import art, diff, markup, palette, theme
from .composer import PromptRow
from .format import safe_notice, strip_escapes

PANEL_LABEL = "Tip:"
PANEL_DIVIDER = "│"
MAX_TOOL_OUTPUT_LINES = 14
FLUSH_INTERVAL = 1 / 24
FILE_TOOLS = ("read_file", "write_file", "edit_file", "list_dir", "glob")


class Block(Static):
    """One entry in the transcript."""

    DEFAULT_CSS = """
    Block {
        width: 1fr;
        height: auto;
        padding: 0;
        margin-bottom: 1;
        background: transparent;
    }
    """


class UserBlock(Block):
    """Something the user typed."""

    DEFAULT_CSS = """
    UserBlock {
        width: 1fr;
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        color: #f8f8f2;
        background: #30343a;
    }
    """

    SENT = "#f8f8f2"

    def __init__(self, text: str):
        self.raw = strip_escapes(text)
        super().__init__(self._body())
        self.shown = self._Static__content.plain

    def on_mount(self) -> None:
        self.restyle()

    def restyle(self) -> None:
        """Sent messages take the theme's own voice and surface."""
        accent = theme.for_widget(self)
        if accent is not None and accent.surface:
            self.styles.background = accent.surface
        else:
            self.styles.background = None
        self.update(self._body())

    def _body(self) -> Text:
        accent = theme.for_widget(self)
        colour = (accent.sent if accent and accent.sent else self.SENT)
        body = Text()
        for index, line in enumerate(self.raw.splitlines() or [""]):
            if index:
                body.append("\n  ")
            else:
                body.append(f"{art.icon('prompt')} ", style="bold")
            body.append(line)
        body.stylize(colour)
        return body

    def get_selection(self, selection):
        """Copy the message, not the marker."""
        picked = selection.extract(self.shown)
        if picked is None:
            return None
        return _unmark(picked, f"{art.icon('prompt')} "), "\n"


class PromptNavigator(Static):
    """Sticky link to the prompt that owns the visible part of the chat."""

    DEFAULT_CSS = """
    PromptNavigator {
        position: absolute;
        offset: 0 0;
        width: 1fr;
        height: 1;
        padding: 0 1;
        color: #f8f8f2;
        background: #3b4149;
        text-overflow: ellipsis;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.target: UserBlock | None = None

    def restyle(self) -> None:
        _wear_surface(self)

    def show_prompt(self, target: UserBlock | None) -> None:
        self.target = target
        if target is None:
            self.display = False
            return
        summary = " ".join(target.raw.split())
        self.update(summary)
        self.display = True

    def on_click(self, event) -> None:
        event.stop()
        if self.target is not None:
            self.screen.query_one(Transcript).jump_to_prompt(self.target)


class BackToBottom(Static):
    """Floating shortcut shown while the transcript is scrolled up."""

    DEFAULT_CSS = """
    BackToBottom {
        position: absolute;
        width: auto;
        height: 1;
        padding: 0 1;
        color: #f8f8f2;
        background: #3b4149;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("↓ Jump to bottom (Ctrl + E)")

    def restyle(self) -> None:
        _wear_surface(self)

    def on_click(self, event) -> None:
        event.stop()
        self.screen.query_one(Transcript).go_to_bottom()


class NoticeBlock(Block):
    """A short system line."""

    def __init__(self, text: str, kind: str = "info"):
        body = Text()
        body.append(f"{art.icon(kind)} ", style="dim")
        body.append(safe_notice(text), style="dim" if kind == "info" else "bold")
        super().__init__(body)


class ArtBlock(Block):
    """Pre-rendered ASCII art, never wrapped."""

    SHIMMER_TICK = 1 / 24

    DEFAULT_CSS = """
    ArtBlock {
        width: 1fr;
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
        background: transparent;
        text-wrap: nowrap;
        text-overflow: clip;
    }
    """

    def __init__(self, text: str, dim: bool = True,
                 reflow: Callable[[int], str] | None = None):
        self.art = text
        self.dim = dim
        self.reflow = reflow
        self._tick = -1
        self._timer = None
        self._played = False
        self._animation = art.banner_animation(text)
        self._span = art.effect_span(self._animation)
        self._heat: dict[tuple[int, int], float] = {}
        super().__init__(self._draw())

    def _lines(self) -> list[str]:
        return self.art.splitlines() or [""]

    def _picture_height(self) -> int:
        """How many rows are the drawing itself."""
        for index, line in enumerate(self._lines()):
            if not line.strip():
                return index
        return len(self._lines())

    def _frame(self, picture: int) -> list[str]:
        """The drawing as it looks this tick, details left untouched."""
        rows = self._lines()
        head, tail = rows[:picture], rows[picture:]
        head, self._heat = art.frame(self._animation, head, self._tick, self._span)
        return head + tail

    def _draw(self) -> Text:
        # Accent colours are already pitched to sit back; dimming muddies them.
        accent = theme.for_widget(self)
        toned = accent is not None and bool(accent.detail)
        base = "dim" if self.dim and not toned else ""
        body = Text(no_wrap=True, overflow="crop")
        picture = self._picture_height()
        self._heat: dict[tuple[int, int], float] = {}
        rows = self._lines() if self._tick < 0 else self._frame(picture)
        ramp = theme.ramp_for(self)
        for index, line in enumerate(rows):
            if index:
                body.append("\n")
            start = len(body.plain)
            lit = self._tick >= 0 and index < picture and bool(line.strip())
            body.append(line, style="" if lit else base)
            if index >= picture or not line.strip():
                self._paint_rules(body, line, start)
            elif lit:
                self._paint_heat(body, line, start, index, ramp)
            else:
                self._paint_art(body, line, start)
        return body

    def _paint_heat(self, body: Text, line: str, start: int, row: int,
                    ramp: theme.Ramp) -> None:
        """One ramp for every effect, so the theme always drives the colour."""
        for column, glyph in enumerate(line):
            if glyph == " ":
                continue
            style = ramp.at(self._heat.get((row, column), 0.0))
            if style:
                body.stylize(style, start + column, start + column + 1)

    def _paint_art(self, body: Text, line: str, start: int) -> None:
        """The drawing itself carries the theme's headline colour."""
        accent = theme.for_widget(self)
        if accent is not None and accent.art:
            body.stylize(accent.art, start, start + len(line))

    def _paint_rules(self, body: Text, line: str, start: int) -> None:
        """Two voices under the drawing: orange keys, quiet cream detail."""
        accent = theme.for_widget(self)
        if accent is None:
            return
        if accent.detail:
            body.stylize(accent.detail, start, start + len(line))
        divider = line.find(PANEL_DIVIDER)
        if divider >= 0 and accent.art:
            body.stylize(accent.art, start + divider + 1, start + len(line))
        heading = line.find(PANEL_LABEL)
        if heading >= 0 and accent.detail:
            body.stylize(f"bold {accent.detail}", start + heading,
                         start + heading + len(PANEL_LABEL))
        keys = _panel_icons()
        for column, glyph in enumerate(line):
            if glyph in art.RULE_GLYPHS:
                body.stylize(accent.rule, start + column, start + column + 1)
            elif glyph in keys and accent.marker:
                body.stylize(accent.marker, start + column, start + column + 1)

    def restyle(self) -> None:
        """Repaint when the user switches theme."""
        if self._tick < 0:
            self.update(self._draw())

    def shimmer(self) -> None:
        """Play an effect, stepping to the next one on every repeat click."""
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._played:
            self._animation = art.next_animation(self._animation)
        self._played = True
        self._span = art.effect_span(self._animation)
        self._tick = 0
        self.update(self._draw())
        self._timer = self.set_interval(self.SHIMMER_TICK, self._advance)

    def _advance(self) -> None:
        self._tick += 1
        if self._tick > self._span:
            self._stop()
            return
        self.update(self._draw())

    def _stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._tick = -1
        self.update(self._draw())

    def on_click(self, event) -> None:
        if not self._on_glyph(event.x, event.y):
            return
        event.stop()
        self.shimmer()

    def _on_glyph(self, x: int, y: int) -> bool:
        """The space around the drawing is not part of it."""
        column = x - self.styles.padding.left
        if column < 0 or not 0 <= y < self._picture_height():
            return False
        line = self._lines()[y]
        return column < len(line) and line[column] != " "

    def on_resize(self, event) -> None:
        """Rebuild rules and columns for the widget's laid-out width."""
        if self.reflow is None:
            return
        self.call_after_refresh(self._reflow)

    def _reflow(self) -> None:
        """Use the settled width, including any space taken by a scrollbar."""
        if self.reflow is None:
            return
        self._stop()
        self.art = self.reflow(max(self.size.width, 1))
        self._animation = art.banner_animation(self.art)
        self._span = art.effect_span(self._animation)
        self._played = False
        self.update(self._draw())

    def on_unmount(self) -> None:
        self._stop()


class ThinkingBlock(Block):
    """Marker only; reasoning stays hidden."""

    def __init__(self) -> None:
        self.buffer = ""
        super().__init__(Text(""))
        self.flush()

    def feed(self, text: str) -> None:
        self.buffer += text

    def restyle(self) -> None:
        self.flush()

    def flush(self) -> None:
        accent = theme.for_widget(self)
        quiet = f"italic {accent.thinking}" if accent and accent.thinking else "dim italic"
        self.update(Text(f"{art.icon('think')} reasoning", style=quiet))


class AnswerBlock(Block):
    """Streamed assistant prose."""

    DEFAULT_CSS = """
    AnswerBlock {
        padding: 0 3;
        margin-bottom: 1;
    }
    """

    def __init__(self) -> None:
        self.buffer = ""
        super().__init__(Text(""))

    def feed(self, text: str) -> None:
        self.buffer += strip_escapes(text)

    def _width(self) -> int:
        return max(self.content_size.width, 4) if self.size.width else markup.DEFAULT_WIDTH

    def on_resize(self, event) -> None:
        self.flush()

    def flush(self) -> None:
        self.update(markup.render(self.buffer.rstrip(), self._width()))

    def get_selection(self, selection):
        """Copy what is on screen, without the panel padding."""
        shown = markup.Markdown(self.buffer.rstrip(), self._width()).plain()
        picked = selection.extract(shown)
        return (markup.trim(picked), "\n") if picked is not None else None

    @property
    def empty(self) -> bool:
        return not self.buffer.strip()


class ToolBlock(Block):
    """A tool call with live output."""

    def __init__(self, name: str, label: str, *, hide_output: bool = False):
        self.hide_output = hide_output
        self.tool = name
        self.label = strip_escapes(label)
        self.output = ""
        self.result = ""
        self.is_error = False
        self.seconds = 0.0
        self.finished = False
        self.artifact_id = ""
        super().__init__(Text(""))
        self.flush()

    def restyle(self) -> None:
        self.flush()

    def feed(self, chunk: str) -> None:
        self.output = (self.output + strip_escapes(chunk))[-8000:]

    def finish(self, result: str, is_error: bool, seconds: float) -> None:
        self.result = strip_escapes(result)
        self.is_error = is_error
        self.seconds = seconds
        self.finished = True

    def flush(self) -> None:
        body = Text()
        mark = art.icon("ok") if self.finished and not self.is_error else (
            art.icon("dot") if self.is_error else art.icon("clock"))
        body.append(f"{mark} ")
        body.append(f"{art.tool_icon(self.tool)} ", style="dim")
        if self.tool in FILE_TOOLS and self.tool not in {"write_file", "edit_file"} \
                and self.label:
            body.append(f"{art.file_icon(self.label)} ", style="dim")
        accent = theme.for_widget(self)
        named = f"bold {accent.tool}" if accent and accent.tool else "bold"
        body.append(self.label or self.tool, style=named)
        if self.finished and self.seconds >= 1:
            body.append(f"  {self.seconds:.0f}s", style="dim")
        detail = "" if self.hide_output and not self.is_error else (
            self.result if self.finished else self.output)
        for line in _tail(detail):
            body.append("\n  ")
            body.append(line, style="dim")
        self.update(body)


class CommandBlock(ToolBlock):
    """A shell command with an explicit running/success/failure state."""

    def __init__(self, name: str, label: str):
        self.expanded = False
        self._saved_key = None
        self._saved_output = ""
        super().__init__(name, label)

    def on_click(self, event) -> None:
        event.stop()
        self.expanded = not self.expanded
        self.flush()

    def _detail(self) -> str:
        if self.artifact_id:
            from ..core import artifacts
            try:
                path = artifacts.location(self.artifact_id)
                stat = path.stat()
                limit = 200_000 if self.expanded else 8000
                key = (self.artifact_id, stat.st_size, stat.st_mtime_ns, limit)
                if key != self._saved_key:
                    self._saved_output = strip_escapes(artifacts.read(self.artifact_id, limit=limit))
                    if self.expanded and stat.st_size > limit:
                        self._saved_output += "\n[Showing first 200 KB; full output is saved in the output artifact.]"
                    self._saved_key = key
                if self._saved_output:
                    return self._saved_output
            except (OSError, ValueError):
                pass
        return self.output or self.result

    def flush(self) -> None:
        # Keep the collapsed preview to two physical rows, even for long lines.
        body = Text(no_wrap=not self.expanded, overflow="crop" if not self.expanded else "fold")
        if not self.finished:
            color, action = palette.YELLOW, "Running"
        elif self.is_error:
            color, action = palette.YELLOW, "Ran"
        elif self.result.startswith("Still running as managed process"):
            color, action = palette.YELLOW, "Working"
        else:
            color, action = palette.GREEN, "Ran"
        body.append(f"{art.icon('bullet')} ", style=color)
        body.append(action, style="bold")
        body.append("(")
        body.append(self.label or "(empty)", style="underline")
        body.append(")")
        body.append("  ▾ collapse" if self.expanded else "  ▸ expand", style="dim")
        if self.finished and self.seconds >= 1:
            body.append(f"  {self.seconds:.0f}s", style="dim")
        lines = self._detail().splitlines()
        if not self.expanded:
            lines = lines[:2]
        for index, line in enumerate(lines):
            body.append("\n")
            body.append(f"{art.icon('corner')} " if index == 0 else "  ", style="dim")
            body.append(line, style="dim")
        self.update(body)


class ChangeBlock(Block):
    """A file change, numbered and highlighted."""

    def __init__(self, path: str, diff_text: str, action: str = ""):
        self.diff_text = diff_text
        self.change = diff.parse(path, diff_text, action)
        self.label = path
        self.result = ""
        self.is_error = False
        self.seconds = 0.0
        self.finished = False
        super().__init__(Text(""))
        self.flush()

    def feed(self, chunk: str) -> None:
        """Changes have no streamed output."""

    def get_selection(self, selection):
        """Copy the code, without the numbers or signs."""
        view = diff.ChangeView(self.change, self._note())
        picked = selection.extract(view.plain(self._width()))
        if picked is None:
            return None
        return diff.strip_gutter(picked, view.gutter()), "\n"

    def code(self) -> str:
        """Every code line, as written."""
        return "\n".join(row.text for row in self.change.rows
                         if row.sign != "-")

    def finish(self, result: str, is_error: bool, seconds: float) -> None:
        self.result = strip_escapes(result)
        self.is_error = is_error
        self.seconds = seconds
        self.finished = True

    def _note(self) -> str:
        if self.finished and self.is_error:
            return f"{art.icon('fail')} {self.result}"
        return ""

    def _width(self) -> int:
        return max(self.size.width or self.container_size.width or 100, 20)

    def on_resize(self, event) -> None:
        self.flush()

    def flush(self) -> None:
        view = diff.ChangeView(self.change, self._note())
        self.update(view.text(self._width()))


class DiffBlock(Block):
    """A pending change awaiting approval."""

    def __init__(self, title: str, diff: str):
        body = Text()
        body.append(f"{art.icon('warn')} {strip_escapes(title)}\n", style="bold")
        for line in strip_escapes(diff).splitlines()[:60]:
            style = "bold" if line.startswith(("+", "-")) and not line.startswith(
                ("+++", "---")) else "dim"
            body.append(f"  {line}\n", style=style)
        super().__init__(body)


class Transcript(VerticalScroll):
    """Scrolling list of blocks."""

    DEFAULT_CSS = """
    Transcript {
        width: 1fr;
        height: 1fr;
        padding: 1 0 0 0;
        background: transparent;
        scrollbar-size-vertical: 1;
    }
    """

    BINDINGS: list = []
    can_focus = False
    can_focus_children = False

    def __init__(self) -> None:
        super().__init__()
        self._live: list[Widget] = []
        self._follow_token = 0
        self._programmatic_follow = False

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        if not self._programmatic_follow and old_value != new_value:
            self._follow_token += 1
        self.call_after_refresh(self.refresh_navigation)

    def on_resize(self, event) -> None:
        self.call_after_refresh(self.refresh_navigation)

    def refresh_navigation(self) -> None:
        """Place and populate the controls for the current viewport."""
        try:
            prompt_link = self.screen.query_one(PromptNavigator)
            bottom_link = self.screen.query_one(BackToBottom)
            input_row = self.screen.query_one(PromptRow)
        except NoMatches:
            return

        away_from_bottom = self.max_scroll_y - self.scroll_y > 1
        bottom_link.display = away_from_bottom
        if not away_from_bottom:
            prompt_link.show_prompt(None)
            return

        # Child virtual regions use the same coordinate system as scroll_y.
        prompts = [child for child in self.children
                   if isinstance(child, UserBlock)
                   and child.virtual_region.y <= self.scroll_y]
        prompt_link.show_prompt(prompts[-1] if prompts else None)

        width = bottom_link.outer_size.width or len("↓ Jump to bottom (Ctrl + E)") + 2
        x = max((self.screen.size.width - width) // 2, 0)
        y = max(self.region.y, input_row.region.y - 3)
        bottom_link.styles.offset = (x, y)

    def go_to_bottom(self) -> None:
        self.scroll_end(animate=False)
        self.call_after_refresh(self.refresh_navigation)

    def _schedule_follow(self) -> None:
        self._follow_token += 1
        token = self._follow_token
        self.call_after_refresh(lambda: self._follow_bottom(token))

    def _follow_bottom(self, token: int) -> None:
        """Follow content after its new wrapped height has been laid out."""
        if token != self._follow_token:
            return
        self._programmatic_follow = True
        try:
            self.scroll_end(animate=False, immediate=True)
        finally:
            self._programmatic_follow = False

    def jump_to_prompt(self, prompt: UserBlock) -> None:
        """Put an exact prompt anchor at the top of the viewport."""
        self.scroll_to_widget(prompt, top=True, animate=False)
        self.call_after_refresh(self.refresh_navigation)

    async def push(self, block: Widget, live: bool = False) -> Widget:
        """Append a block, following it only when already at the bottom."""
        follow = self.is_vertical_scroll_end
        await self.mount(block)
        if live:
            self._live.append(block)
        if follow:
            self._schedule_follow()
        self.call_after_refresh(self.refresh_navigation)
        return block

    def flush_live(self) -> None:
        """Redraw streaming blocks."""
        if not self._live:
            return
        follow = self.is_vertical_scroll_end
        for block in list(self._live):
            flush = getattr(block, "flush", None)
            if flush:
                flush()
        if follow:
            self._schedule_follow()

    def settle(self) -> None:
        """Stop tracking finished blocks."""
        self.flush_live()
        self._live.clear()

    def reset(self) -> None:
        """Drop every block."""
        self._live.clear()
        self.remove_children()


def _wear_surface(widget) -> None:
    """Float above the transcript on the theme's panel colour."""
    accent = theme.for_widget(widget)
    widget.styles.background = accent.surface if accent and accent.surface else None
    widget.styles.color = accent.on_surface if accent and accent.on_surface else None


def _panel_icons() -> set[str]:
    """The little glyphs that key the rows under the banner."""
    return {art.icon(name) for name in ("dir", "link", "info")}


def _unmark(text: str, marker: str) -> str:
    """Drop the prompt marker from whole lines."""
    out = []
    for line in text.splitlines():
        if line.startswith(marker):
            out.append(line[len(marker):])
        elif line.startswith("  "):
            out.append(line[2:])
        else:
            out.append(line)
    return "\n".join(out)


def _tail(text: str) -> list[str]:
    lines = [line.rstrip() for line in (text or "").splitlines() if line.strip()]
    if len(lines) <= MAX_TOOL_OUTPUT_LINES:
        return lines
    hidden = len(lines) - MAX_TOOL_OUTPUT_LINES
    return lines[:4] + [f"… {hidden} lines hidden …"] + lines[-(MAX_TOOL_OUTPUT_LINES - 5):]
