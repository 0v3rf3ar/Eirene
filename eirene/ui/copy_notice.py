"""Brief clipboard feedback in the bottom-right corner."""

from textual.geometry import Size
from textual.widgets import Static


class CopyNotice(Static):
    DEFAULT_CSS = """
    CopyNotice {
        position: absolute;
        overlay: screen;
        layer: notification;
        width: auto;
        height: 1;
        padding: 0 1;
        color: $text;
        background: $background;
        display: none;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self.message = ""
        self._hide_timer = None

    def show_count(self, count: int) -> None:
        self.message = f"copied {count} characters"
        self.update(self.message)
        self.display = True
        self.place(self.screen.size)
        if self._hide_timer is not None:
            self._hide_timer.stop()
        self._hide_timer = self.set_timer(2, self._hide)

    def place(self, size: Size) -> None:
        self.styles.offset = (max(size.width - len(self.message) - 2, 0),
                              max(size.height - 1, 0))

    def _hide(self) -> None:
        self.display = False
        self._hide_timer = None

    def on_unmount(self) -> None:
        if self._hide_timer is not None:
            self._hide_timer.stop()
