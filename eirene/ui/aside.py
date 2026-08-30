"""The /btw window."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text
from textual import events
from textual.containers import Container, VerticalScroll
from textual.widgets import Static

from . import art, markup, theme
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
        self._content: Text | None = None
        self._content_width: int | None = None
        self._width = markup.DEFAULT_WIDTH

    def compose(self):
        with AsideBody():
            yield Static(Text(""), id="aside-body")
        yield CloseButton(Text(CLOSE, style="bold"))

    def on_mount(self) -> None:
        self.display = False
        self.restyle()

    def restyle(self) -> None:
        """Use the theme's own surface so light themes stay light."""
        accent = theme.for_widget(self)
        background = (accent.surface if accent and accent.surface
                      else POPUP_BACKGROUND)
        foreground = (accent.on_surface if accent and accent.on_surface
                      else FOREGROUND)
        self.styles.background = background
        self.styles.color = foreground
        self.close_button.styles.background = background
        self.close_button.styles.color = foreground
        if self.display:
            self.refresh_body()

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
        self._content = None
        self._content_width = None
        self.question = strip_escapes(question)
        self.answer = ""
        self.note = "asking…"
        self.failed = False
        self.display = True
        self._place()
        self.refresh_body()

    def show_content(self, content: Text) -> None:
        """Show a finished, selectable panel without adding it to the chat."""
        self._content = content
        self._content_width = max(
            (cell_len(line) for line in content.plain.splitlines()),
            default=0,
        )
        self.question = ""
        self.answer = ""
        self.note = ""
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
        self._content = None
        self._content_width = None
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
        if self._content_width is not None:
            wanted = self._content_width + 4
        else:
            wanted = int(screen.width * WIDTH_SHARE)
        wanted = max(min(wanted, MAX_WIDTH), MIN_WIDTH)
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
        if self._content is not None:
            self.body.update(self._content)
            self._place()
            return
        room = self._width
        accent = theme.for_widget(self)
        text_colour = (accent.on_surface if accent and accent.on_surface
                       else TEXT)
        question_colour = (accent.thinking if accent and accent.thinking
                           else QUESTION)
        body = Text(style=text_colour)
        head = Text()
        head.append(f"{art.icon('think')} btw  ", style=f"bold {text_colour}")
        head.append(self.question, style=question_colour)
        head.truncate(max(room - len(CLOSE) - 2, 4), overflow="ellipsis")
        body.append_text(head)
        if self.note:
            body.append(f"\n  {self.note}", style=f"italic {question_colour}")
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
