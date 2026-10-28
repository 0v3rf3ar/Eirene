"""Bottom dock: rules, input and mode line."""

from __future__ import annotations

from pathlib import Path
from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.widgets import Static, TextArea

from ..core.modes import Mode
from ..core.attachments import dropped_paths
from . import art, theme
from .format import pasted_label

MAX_ROWS = 10
FOLD_LINES = 4
FOLD_CHARS = 240
MASK = "•"


class Rule(Static):
    """Full-width horizontal separator."""

    DEFAULT_CSS = """
    Rule {
        width: 1fr;
        height: 1;
        background: transparent;
    }
    """

    def on_mount(self) -> None:
        self._draw()

    def on_resize(self, event: events.Resize) -> None:
        self._draw()

    def restyle(self) -> None:
        """Pick up the colours of a theme the user just chose."""
        self._draw()

    def _draw(self) -> None:
        width = max(self.size.width, 1)
        accent = theme.for_widget(self)
        style = accent.rule if accent else "dim"
        self.update(Text("─" * width, style=style))


class ModeLine(Static):
    """Mode indicator under the input."""

    DEFAULT_CSS = """
    ModeLine {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(""))
        self.mode = Mode.MANUAL
        self.detail = ""

    def show(self, mode: Mode, detail: str = "") -> None:
        self.mode = mode
        self.detail = detail
        body = Text()
        body.append(f"  {mode.icon} {mode.label} on", style="dim")
        if self.detail:
            body.append(f"  | {self.detail}", style="dim")
        self.update(body)


# The diamond turns while subagents work: outline, half, solid, half.
DIAMOND_FRAMES = ("◇", "◈", "◆", "◈")


def describe_subagents(subagents: dict[str, dict], tick: int | None = None) -> Text:
    """How many subagents this session has started; the icon turns while any is working."""
    count = len(subagents)
    working = any(row["status"] == "running" for row in subagents.values())
    icon = art.icon("agent")
    if working and tick is not None and not art.ACCESSIBLE:
        icon = DIAMOND_FRAMES[tick % len(DIAMOND_FRAMES)]
    return Text(f"  {icon} {count} subagent{'s' if count != 1 else ''}",
                style="" if working else "dim")


class SubagentLine(Static):
    """This session's subagent count, under the mode line; click for /subagents."""

    DEFAULT_CSS = """
    SubagentLine {
        width: 1fr;
        height: 1;
        padding: 0 1;
        background: transparent;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(""))
        self._shown: str | None = None
        self._tick = 0

    def on_mount(self) -> None:
        self.set_interval(0.5, self.refresh_subagents)

    def refresh_subagents(self) -> None:
        agent = getattr(self.app, "agent", None)
        subagents = getattr(getattr(agent, "session", None), "subagents", None) or {}
        config = getattr(agent, "config", None)
        still = config is not None and config.get("reduce_motion", False)
        self._tick += 1
        line = describe_subagents(subagents, None if still else self._tick) if subagents else Text("")
        if line.markup != self._shown:
            self._shown = line.markup
            self.display = bool(subagents)
            self.update(line)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.app._start_command("/subagents")


class Marker(Static):
    """The ❯ in front of the input."""

    DEFAULT_CSS = """
    Marker {
        width: 3;
        height: 1;
        padding: 0 1;
        background: transparent;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(art.icon("prompt"), style="bold"))

    def on_mount(self) -> None:
        self.restyle()

    def restyle(self) -> None:
        """The caret takes the theme's accent colour, when it has one."""
        accent = theme.for_widget(self)
        style = f"bold {accent.marker}" if accent else "bold"
        self.update(Text(art.icon("prompt"), style=style))


class Prompt(TextArea):
    """Multiline entry with history and folded pastes."""

    DEFAULT_CSS = """
    Prompt {
        width: 1fr;
        height: auto;
        max-height: 10;
        border: none;
        padding: 0;
        background: transparent;
        scrollbar-size-vertical: 0;
    }
    Prompt:focus {
        border: none;
        background: transparent;
    }
    Prompt .text-area--placeholder {
        color: #777777;
        text-style: none;
    }
    Prompt:light .text-area--placeholder { color: #707070; }
    Prompt:ansi .text-area--placeholder {
        color: ansi_bright_black;
        text-style: dim;
    }
    """

    BINDINGS: list = []

    class Sent(Message):
        """Text the user sent."""

        def __init__(self, text: str, files: list[dict] | None = None):
            super().__init__()
            self.text = text
            self.files = files or []

    class SuggestionAccepted(Message):
        """Accept the optional follow-up without submitting it."""

    class FilesDropped(Message):
        """Files supplied through a terminal paste/drop."""

        def __init__(self, paths: list[Path]):
            super().__init__()
            self.paths = paths

    class Draft(Message):
        """The pending text changed."""

        def __init__(self, text: str, suggest: bool = True):
            super().__init__()
            self.text = text
            self.suggest = suggest

    class Navigate(Message):
        """Up or down while a menu is open."""

        def __init__(self, delta: int):
            super().__init__()
            self.delta = delta

    class Accept(Message):
        """Enter or tab while a menu is open."""

        def __init__(self, run: bool):
            super().__init__()
            self.run = run

    def __init__(self) -> None:
        super().__init__(soft_wrap=True, tab_behavior="focus", compact=True,
                         show_line_numbers=False, id="prompt")
        self.recent: list[str] = []
        self.menu_open = False
        self.prompt_suggestion = ""
        self._position = 0
        self._pending = ""
        self._secret = False
        self._silent: str | None = None
        self._pastes: list[tuple[str, str]] = []
        self._files: dict[str, dict] = {}
        self._command_length = 0

    # value

    @property
    def prompt_suggestion(self) -> str:
        return getattr(self, "_prompt_suggestion", "")

    @prompt_suggestion.setter
    def prompt_suggestion(self, value: str) -> None:
        self._prompt_suggestion = value
        self.placeholder = "" if getattr(self, "_secret", False) else value
        self.refresh(layout=True)

    def get_content_height(self, container, viewport, width: int) -> int:
        if self.placeholder and not self.text:
            return min(MAX_ROWS, max(1, len(Text(str(self.placeholder)).wrap(
                self.app.console, max(width, 1)))))
        return super().get_content_height(container, viewport, width)

    @property
    def secret(self) -> bool:
        return self._secret

    @secret.setter
    def secret(self, hide: bool) -> None:
        self._secret = bool(hide)
        self.placeholder = "" if hide else self.prompt_suggestion
        self._line_cache.clear()
        self.refresh()

    def mark_command(self, length: int) -> None:
        """Bold the first `length` characters: a complete slash command name."""
        if length != self._command_length:
            self._command_length = length
            self._line_cache.clear()
            self.refresh()

    def get_line(self, line_index: int):
        """Mask the text while a secret is wanted."""
        line = super().get_line(line_index)
        if not self._secret:
            line = line.copy()
            if line_index == 0 and self._command_length:
                line.stylize("bold", 0, self._command_length)
            for token in self._files:
                column = line.plain.find(token)
                while column >= 0:
                    line.stylize("bold italic", column, column + len(token))
                    column = line.plain.find(token, column + len(token))
        if not self._secret or not self.text:
            return line
        return Text(MASK * len(line.plain), end="", no_wrap=True)

    @property
    def value(self) -> str:
        return self.text

    @value.setter
    def value(self, text: str) -> None:
        self._load(text)
        self.move_cursor(self.document.end)
        self._announce(suggest=False)

    def recall_from(self, inputs: list[str]) -> None:
        """Seed the up-arrow history from a resumed session."""
        self.recent = [text for text in inputs if text.strip()]
        self._position = len(self.recent)
        self._pending = ""

    def remember(self, text: str) -> None:
        """Add a submitted, non-secret entry to up/down history."""
        text = text.strip()
        sensitive_command = text.lower().startswith("/search-api ")
        if text and not self._secret and not sensitive_command:
            self.recent.append(text)
        self._position = len(self.recent)
        self._pending = ""

    def unfold(self, text: str) -> str:
        """Put folded pastes back."""
        for token, real in self._pastes:
            if token in text:
                text = text.replace(token, real, 1)
        return text

    def clear_draft(self) -> None:
        self._load("")
        self._pastes.clear()
        self._files.clear()
        self._announce(suggest=False)

    def attach_file(self, item: dict) -> None:
        """Insert a filename token backed by stored attachment metadata."""
        from .format import strip_escapes
        name = strip_escapes(item["name"]).replace("\n", " ").replace("\r", " ")
        token = f"[{name}]"
        index = 2
        while token in self._files or token in self.text:
            token = f"[{name} ({index})]"
            index += 1
        self._files[token] = {**item, "token": token}
        self.insert(token)
        self._line_cache.clear()
        self.refresh()
        self._announce(suggest=False)

    def _announce(self, suggest: bool = True) -> None:
        self.post_message(self.Draft(self.text, suggest and not self._secret))

    # events

    def _delete_via_keyboard(self, start, end):
        """Delete folded pastes as a unit when a deletion touches their label."""
        start, end = sorted((start, end))
        if start != end:
            tokens = {token for token, _ in self._pastes} | self._files.keys()
            for row, line in enumerate(self.document.lines):
                for token in tokens:
                    column = line.find(token)
                    while column >= 0:
                        token_start = (row, column)
                        token_end = (row, column + len(token))
                        if start < token_end and end > token_start:
                            start = min(start, token_start)
                            end = max(end, token_end)
                        column = line.find(token, column + len(token))
        return super()._delete_via_keyboard(start, end)

    def _load(self, text: str) -> None:
        """Set the text without reopening the menu."""
        self._silent = text
        self.load_text(text)

    def on_text_area_changed(self, event) -> None:
        """Catch edits the key handler never sees, like backspace."""
        event.stop()
        expected, self._silent = self._silent, None
        if expected is not None and self.text == expected:
            return
        self._announce()

    async def _on_paste(self, event: events.Paste) -> None:
        """Fold a big paste into a short token."""
        event.stop()
        event.prevent_default()
        text = event.text.replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        if not self._secret and not getattr(self.app, "_text_future", None):
            paths = dropped_paths(text, self.app.sandbox.root)
            if paths:
                self.post_message(self.FilesDropped(paths))
                return
        if text.count("\n") + 1 >= FOLD_LINES or len(text) >= FOLD_CHARS:
            token = pasted_label(text)
            self._pastes.append((token, text))
            self.insert(token)
        else:
            self.insert(text)
        self._announce()

    async def _on_key(self, event: events.Key) -> None:
        key = event.key
        if (key in {"tab", "right"} and self.prompt_suggestion and not self.text
                and not self.menu_open and not self._secret):
            event.stop()
            event.prevent_default()
            self.post_message(self.SuggestionAccepted())
            return
        if key == "enter":
            event.stop()
            event.prevent_default()
            self._submit_or_newline()
            return
        if key == "tab" and self.menu_open:
            event.stop()
            event.prevent_default()
            self.post_message(self.Accept(run=False))
            return
        if key in ("up", "down"):
            event.stop()
            event.prevent_default()
            self._arrow(-1 if key == "up" else 1)
            return
        before = self.text
        await super()._on_key(event)
        if self.text != before:
            self._announce()

    def _submit_or_newline(self) -> None:
        if self.menu_open:
            self.post_message(self.Accept(run=True))
            return
        if self._continues():
            self.insert("\n")
            self._announce()
            return
        raw = self.text.strip()
        if not raw:
            return
        self.remember(raw)
        text = self.unfold(raw)
        files = [item for token, item in self._files.items() if token in raw]
        self._load("")
        self._pastes.clear()
        self._files.clear()
        self._announce(suggest=False)
        self.post_message(self.Sent(text, files))

    def _continues(self) -> bool:
        """A trailing backslash means a new line."""
        row, column = self.cursor_location
        line = self.document.get_line(row)
        if column <= 0 or column > len(line) or not line[:column].endswith("\\"):
            return False
        self.action_delete_left()
        return True

    def _arrow(self, delta: int) -> None:
        if self.menu_open:
            self.post_message(self.Navigate(delta))
            return
        location = self.cursor_location
        if delta < 0 and not self.navigator.is_first_wrapped_line(location):
            self.action_cursor_up()
            return
        if delta > 0 and not self.navigator.is_last_wrapped_line(location):
            self.action_cursor_down()
            return
        self._recall(delta)

    def _recall(self, delta: int) -> None:
        if not self.recent:
            return
        if self._position >= len(self.recent) and delta < 0:
            self._pending = self.text
        position = self._position + delta
        if position < 0 or position > len(self.recent):
            return
        self._position = position
        text = self._pending if position >= len(self.recent) else self.recent[position]
        self._load(text)
        self.move_cursor(self.document.end)
        self._announce(suggest=False)


class PromptRow(Horizontal):
    """Marker and input side by side."""

    DEFAULT_CSS = """
    PromptRow {
        width: 1fr;
        height: auto;
        background: transparent;
    }
    """


class Composer(Container):
    """Everything docked at the bottom."""

    DEFAULT_CSS = """
    Composer {
        width: 1fr;
        height: auto;
        dock: bottom;
        background: transparent;
    }
    """

    def __init__(self, *children):
        super().__init__()
        self._extras = children

    def compose(self):
        for widget in self._extras:
            yield widget
        from .status import ContextIndicator
        yield ContextIndicator()
        yield Rule()
        with PromptRow():
            yield Marker()
            yield Prompt()
        yield Rule()
        yield ModeLine()
        yield SubagentLine()
        from .processes import ProcessBar
        yield ProcessBar()

    def on_resize(self):
        from .companion import Companion
        for companion in self.app.query(Companion):
            companion.call_after_refresh(companion.position_portrait)

    @property
    def prompt(self) -> Prompt:
        return self.query_one(Prompt)

    @property
    def mode_line(self) -> ModeLine:
        return self.query_one(ModeLine)
