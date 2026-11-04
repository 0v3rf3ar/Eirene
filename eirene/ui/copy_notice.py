"""Brief clipboard feedback in the bottom-right corner."""

from rich.cells import cell_len
from textual.geometry import Size
from textual.widgets import Static

# Over SSH the copy travels to the user's computer as an OSC 52 escape, which some
# terminals refuse. Holding Shift (Option in some macOS terminals) bypasses mouse
# reporting, so the terminal's own selection and copy work instead.
REMOTE_HINT = "if it didn't paste, hold Shift while selecting to use your terminal's copy"


class CopyNotice(Static):
    DEFAULT_CSS = """
    CopyNotice {
        position: absolute;
        overlay: screen;
        layer: notification;
        width: auto;
        max-width: 100%;
        height: 1;
        padding: 0 1;
        color: $text;
        background: $background;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("", markup=False)
        self.message = ""
        self._hide_timer = None

    def show_count(self, count: int, *, remote: bool = False) -> None:
        noun = "character" if count == 1 else "characters"
        if remote:
            self.show(f"copied {count} {noun} to your computer · {REMOTE_HINT}", seconds=5)
        else:
            self.show(f"copied {count} {noun}")

    def show(self, message: str, *, seconds: float = 2) -> None:
        self.message = message
        self.update(message)
        self.display = True
        self.place(self.screen.size)
        if self._hide_timer is not None:
            self._hide_timer.stop()
        self._hide_timer = self.set_timer(seconds, self._hide)

    def place(self, size: Size) -> None:
        self.styles.offset = (max(size.width - cell_len(self.message) - 2, 0),
                              max(size.height - 1, 0))

    def _hide(self) -> None:
        self.display = False
        self._hide_timer = None

    def on_unmount(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.stop()
