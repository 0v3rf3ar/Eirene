"""Paged command output, available during execution and after session resume."""
from rich.text import Text
from textual.screen import ModalScreen
from textual.containers import VerticalScroll
from textual.widgets import Static
from ..core import artifacts
from .format import strip_escapes
from .window import DraggableWindow


class OutputScreen(ModalScreen):
    DEFAULT_CSS = """
    OutputScreen { align: center middle; }
    OutputScreen > DraggableWindow {
        width: 90%; max-width: 140; height: 85%;
        border: round $primary; background: $surface; padding: 1;
    }
    OutputScreen VerticalScroll { height: 1fr; margin-top: 1; background: $surface; }
    OutputScreen #output-title { height: auto; max-height: 4; text-style: bold; }
    OutputScreen #output-state { height: auto; color: $text-muted; }
    OutputScreen #output-help { height: auto; margin-top: 1; color: $text-muted; }
    """
    BINDINGS = [("escape", "close", "Close"), ("pagedown", "next", "Next page"),
                ("pageup", "previous", "Previous page"), ("s", "stop", "Stop command")]
    PAGE = 50000

    def __init__(self, card):
        super().__init__()
        self.card = card
        self.byte_offset = 0

    def compose(self):
        with DraggableWindow():
            yield Static(Text(self.card.label), id="output-title")
            yield Static("", id="output-state", markup=False)
            with VerticalScroll():
                yield Static("", id="output-body", markup=False)
            yield Static("", id="output-help", markup=False)

    def on_mount(self):
        self.refresh_output()
        self.set_interval(0.25, self.refresh_output)
        self.query_one(VerticalScroll).focus()

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
        stoppable = hasattr(self.card, "stop") and not self.card.finished
        self.query_one("#output-help", Static).update(
            "↑/↓ scroll · PgUp/PgDn page" + (" · S stop" if stoppable else "") + " · Esc close")
        page = f" · page {self.byte_offset // self.PAGE + 1}" if self.byte_offset else ""
        self.query_one("#output-state", Static).update(f"{state} · {self.card.seconds:.0f}s{page}")
        self.query_one("#output-body", Static).update(Text(strip_escapes(body) or "(no output)"))

    def action_next(self):
        self.byte_offset += self.PAGE
        self.refresh_output()

    def action_previous(self):
        self.byte_offset = max(0, self.byte_offset - self.PAGE)
        self.refresh_output()

    def action_close(self):
        self.dismiss()

    async def action_stop(self):
        """Stop a running command shown here; the view stays open on its final output."""
        if hasattr(self.card, "stop") and not self.card.finished:
            self.app.say(await self.card.stop())
            self.refresh_output()
