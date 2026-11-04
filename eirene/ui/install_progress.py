"""A live bar for downloads made by /plugin marketplace add, install and update."""

from __future__ import annotations

from rich.text import Text

from .chat import Block
from .update_card import progress_bar


class InstallProgress(Block):
    """Redraws in place; it only ever moves forward."""

    def __init__(self, title: str):
        self.title = title
        self.stage = "Connecting"
        self.percent = 0
        super().__init__(self._text())

    def advance(self, stage: str, fraction: float) -> None:
        percent = max(self.percent, min(100, int(fraction * 100)))
        if (percent, stage) != (self.percent, self.stage):
            self.percent, self.stage = percent, stage
            self.update(self._text())

    def _text(self) -> Text:
        body = Text(f"{self.title}\n", style="bold")
        body.append(progress_bar(self.percent), style="bold")
        body.append(f" {self.percent:>3}%", style="bold")
        body.append(f"  {self.stage}", style="dim")
        return body
