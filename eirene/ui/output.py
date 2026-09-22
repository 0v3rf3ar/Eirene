"""Paged command output, available during execution and after session resume."""
from rich.text import Text
from textual.screen import ModalScreen
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.widgets import Button, Static
from ..core import artifacts
from .format import strip_escapes


class OutputScreen(ModalScreen):
    DEFAULT_CSS = """
    OutputScreen { align: center middle; }
    OutputScreen > Vertical { width: 90%; height: 85%; border: round $accent; background: $surface; padding: 1; }
    OutputScreen VerticalScroll { height: 1fr; }
    OutputScreen Horizontal { height: 3; }
    OutputScreen #output-title { height: auto; max-height: 4; }
    """
    BINDINGS = [("escape", "close", "Close"), ("pagedown", "next", "Next page"),
                ("pageup", "previous", "Previous page")]
    PAGE = 50000

    def __init__(self, card):
        super().__init__()
        self.card = card
        self.byte_offset = 0

    def compose(self):
        with Vertical():
            yield Static(Text(self.card.label), id="output-title")
            yield Static("", id="output-state")
            with VerticalScroll():
                yield Static("", id="output-body", markup=False)
            with Horizontal():
                yield Button("Previous", id="previous")
                yield Button("Next", id="next")
                yield Button("Close", id="close")

    def on_mount(self):
        self.refresh_output()
        self.set_interval(0.25, self.refresh_output)

    def refresh_output(self):
        artifact_id = getattr(self.card, "artifact_id", "")
        body = self.card.result if self.card.finished else self.card.output
        if artifact_id:
            try:
                body = artifacts.read(artifact_id, self.byte_offset, self.PAGE)
            except (ValueError, OSError):
                body = "Saved output unavailable.\n" + body
        else:
            body = body[self.byte_offset:self.byte_offset + self.PAGE]
        state = "Running" if not self.card.finished else ("Failed" if self.card.is_error else "Finished")
        self.query_one("#output-state", Static).update(f"{state} · offset {self.byte_offset} · {self.card.seconds:.1f}s")
        self.query_one("#output-body", Static).update(Text(strip_escapes(body) or "(no output)"))

    def action_next(self):
        self.byte_offset += self.PAGE
        self.refresh_output()

    def action_previous(self):
        self.byte_offset = max(0, self.byte_offset - self.PAGE)
        self.refresh_output()

    def action_close(self):
        self.dismiss()

    def on_button_pressed(self, event):
        {"next": self.action_next, "previous": self.action_previous,
         "close": self.action_close}[event.button.id]()
