"""A small, visible activity bar shared by manual and automatic compaction."""

from rich.text import Text
from textual.widgets import Static


class CompactionProgress(Static):
    DEFAULT_CSS = """
    CompactionProgress {
        width: 42;
        max-width: 100%;
        height: 3;
        margin: 0 0 0 1;
        background: transparent;
    }
    """

    def __init__(self):
        super().__init__()
        self.stage = "preparing"
        self._tick = 0

    def on_mount(self):
        self.set_interval(0.12, self._advance)

    def _advance(self):
        self._tick += 1
        self.refresh()

    def set_stage(self, stage: str) -> None:
        self.stage = stage
        self.refresh()

    def render(self) -> Text:
        width = max(1, min(30, self.size.width - 2))
        reduced = self.is_mounted and self.app.config.get("reduce_motion", False)
        pulse = min(6, width)
        span = max(1, width - pulse)
        position = span // 2 if reduced else span - abs(self._tick % (2 * span) - span)
        bar = Text("compacting context\n", style="bold")
        bar.append(self.stage + "\n", style="dim")
        bar.append("[", style="dim")
        for index in range(width):
            lit = self.stage == "complete" or position <= index < position + pulse
            bar.append("━" if lit else "─", style="bold cyan" if lit else "dim")
        bar.append("]", style="dim")
        bar.no_wrap = True
        bar.overflow = "ellipsis"
        return bar
