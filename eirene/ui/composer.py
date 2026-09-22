"""Bottom dock: rules, input and mode line."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.containers import Container, Horizontal
from textual.message import Message
from textual.widgets import Static, TextArea

from ..core.modes import Mode
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

        def __init__(self, text: str):
            super().__init__()
            self.text = text

    class SuggestionAccepted(Message):
        """Accept the optional follow-up without submitting it."""

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

    def get_line(self, line_index: int):
        """Mask the text while a secret is wanted."""
        line = super().get_line(line_index)
        if not self._secret:
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
        if text and not self._secret:
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
        self._announce(suggest=False)

    def _announce(self, suggest: bool = True) -> None:
        self.post_message(self.Draft(self.text, suggest and not self._secret))

    # events

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
        self._load("")
        self._pastes.clear()
        self._announce(suggest=False)
        self.post_message(self.Sent(text))

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
        rows = self.document.line_count
        row = self.cursor_location[0]
        if rows > 1:
            if delta < 0 and row > 0:
                self.action_cursor_up()
                return
            if delta > 0 and row < rows - 1:
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
        yield Rule()
        with PromptRow():
            yield Marker()
            yield Prompt()
        yield Rule()
        yield ModeLine()

    @property
    def prompt(self) -> Prompt:
        return self.query_one(Prompt)

    @property
    def mode_line(self) -> ModeLine:
        return self.query_one(ModeLine)
