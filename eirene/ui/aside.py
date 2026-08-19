"""The /btw window."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from . import art, markup
from .format import strip_escapes
from .palette import FOREGROUND

CLOSE = "[x]"
MAX_WIDTH = 100
MIN_WIDTH = 24
TEXT = FOREGROUND
QUESTION = "#8b949e"
POPUP_BACKGROUND = "#000000"
WIDTH_SHARE = 0.8
HEIGHT_SHARE = 0.7


class CloseButton(Static):
    """The [x], pinned to the corner."""

    DEFAULT_CSS = f"""
    CloseButton {{
        layer: close;
        width: {len(CLOSE)};
        height: 1;
        padding: 0;
        background: {POPUP_BACKGROUND};
        color: {FOREGROUND};
        text-style: bold;
    }}
    """


class AsideBody(VerticalScroll):
    """The scrolling part."""

    DEFAULT_CSS = """
    AsideBody {
        layer: base;
        width: 1fr;
        height: auto;
        background: transparent;
        scrollbar-size-vertical: 1;
    }
    """

    BINDINGS: list = []
    can_focus = False


class AsidePanel(Container):
    """A window floating over the chat, covering only its own area."""

    DEFAULT_CSS = f"""
    AsidePanel {{
        layer: overlay;
        layers: base close;
        width: auto;
        height: auto;
        padding: 0 1;
        background: {POPUP_BACKGROUND};
        border: round $primary;
        display: none;
    }}
    """

    def __init__(self) -> None:
        super().__init__()
        self.question = ""
        self.answer = ""
        self.note = "asking…"
        self.failed = False
        self._width = markup.DEFAULT_WIDTH

    def compose(self):
        with AsideBody():
            yield Static(Text(""), id="aside-body")
        yield CloseButton(Text(CLOSE, style="bold"))

    def on_mount(self) -> None:
        self.display = False

    @property
    def open(self) -> bool:
        return bool(self.display)

    @property
    def body(self) -> Static:
        return self.query_one("#aside-body", Static)

    @property
    def close_button(self) -> CloseButton:
        return self.query_one(CloseButton)

    @property
    def window(self) -> "AsidePanel":
        return self

    def ask(self, question: str) -> None:
        """Show the window with a pending answer."""
        self.question = strip_escapes(question)
        self.answer = ""
        self.note = "asking…"
        self.failed = False
        self.display = True
        self._place()
        self.refresh_body()

    def feed(self, text: str) -> None:
        self.answer += strip_escapes(text)

    def finish(self, answer: str = "", failed: bool = False) -> None:
        if answer:
            self.answer = strip_escapes(answer)
        self.failed = failed
        self.note = ""
        self.refresh_body()

    def close(self) -> None:
        self.display = False
        self.question = ""
        self.answer = ""
        self.note = ""

    def _place(self, screen=None) -> None:
        """Centre the window and pin the button to its corner."""
        try:
            screen = screen or self.app.size
        except Exception:  # noqa: BLE001
            return
        if not screen.width or not screen.height:
            return
        wanted = max(min(int(screen.width * WIDTH_SHARE), MAX_WIDTH), MIN_WIDTH)
        width = max(min(wanted, screen.width), 8)
        self._width = max(width - 4, 4)
        self.styles.width = width
        self.query_one(AsideBody).styles.max_height = max(
            min(int(screen.height * HEIGHT_SHARE), screen.height - 2), 1)
        height = min(self.outer_size.height or 0, screen.height)
        self.styles.offset = (max((screen.width - width) // 2, 0),
                              max((screen.height - height) // 2, 0))
        self.close_button.styles.offset = (max(self._width - len(CLOSE), 0), 0)

    def on_resize(self, event: events.Resize) -> None:
        self._place()

    def refresh_body(self) -> None:
        """One Text, so the answer can be selected."""
        if not self.display:
            return
        room = self._width
        body = Text(style=TEXT)
        head = Text()
        head.append(f"{art.icon('think')} btw  ", style=f"bold {TEXT}")
        head.append(self.question, style=QUESTION)
        head.truncate(max(room - len(CLOSE) - 2, 4), overflow="ellipsis")
        body.append_text(head)
        if self.note:
            body.append(f"\n  {self.note}", style=f"italic {QUESTION}")
        if self.answer:
            body.append("\n")
            body.append_text(markup.render(self.answer.rstrip(), room))
        self.body.update(body)
        self._place()

    def on_click(self, event: events.Click) -> None:
        """The [x] or the title row closes it."""
        if not self.display:
            return
        if event.y <= 0 or isinstance(event.widget, CloseButton):
            event.stop()
            self.close()
