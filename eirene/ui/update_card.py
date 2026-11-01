"""A live card for /update: versions, download progress and each verified step."""

from __future__ import annotations

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.text import Text

from . import art
from .chat import Block

BAR = 24


def progress_bar(percent: int, width: int = BAR) -> str:
    percent = max(0, min(100, percent))
    filled = round(width * percent / 100)
    full, empty = ("#", "-") if art.ACCESSIBLE else ("█", "░")
    return full * filled + empty * (width - filled)


class UpdateCard(Block):
    """Redraws in place as the update moves through its steps."""

    def __init__(self, current: str, channel: str):
        self.current = current
        self.channel = channel
        self.latest = ""
        self.steps: list[tuple[str, str]] = []  # (state, text): ok, fail, busy
        self.percent: int | None = None
        self.download_bytes = 0
        self.footer = ""
        self.failed = False
        super().__init__(self._render_card())

    # state changes

    def step(self, text: str, state: str = "ok") -> None:
        if self.steps and self.steps[-1][0] == "busy":
            self.steps.pop()
        self.steps.append((state, text))
        self.failed = self.failed or state == "fail"
        self._redraw()

    def found(self, latest: str) -> None:
        self.latest = latest
        self._redraw()

    def progress(self, count: int, total: int) -> None:
        self.download_bytes = total or count
        self.percent = int(count * 100 / total) if total else None
        self._redraw()

    def finish(self, footer: str) -> None:
        if self.steps and self.steps[-1][0] == "busy":
            self.steps.pop()
        self.percent = None
        self.footer = footer
        self._redraw()

    # drawing

    def _redraw(self) -> None:
        self.update(self._render_card())

    def _render_card(self) -> Panel:
        rows: list[Text] = []
        versions = Text()
        versions.append(f"{self.current}", style="bold")
        if self.latest:
            versions.append(f"  {art.icon('arrow')}  ", style="dim")
            versions.append(self.latest, style="bold")
        versions.append(f"   {self.channel} channel", style="dim")
        rows.append(versions)
        rows.append(Text(""))
        for state, text in self.steps:
            line = Text()
            if state == "busy":
                line.append(f"{art.icon('dot')} {text}…", style="dim")
            else:
                line.append(f"{art.icon('ok' if state == 'ok' else 'fail')} ",
                            style="bold" if state == "ok" else "bold red")
                line.append(text, style="" if state == "ok" else "red")
            rows.append(line)
        if self.percent is not None:
            bar = Text()
            bar.append(progress_bar(self.percent), style="bold")
            bar.append(f" {self.percent:>3}%", style="bold")
            if self.download_bytes:
                bar.append(f"  {self.download_bytes / 1_000_000:.1f} MB", style="dim")
            rows.append(bar)
        if self.footer:
            rows.append(Text(""))
            rows.append(Text(self.footer, style="bold"))
        return Panel(Group(*rows), title=Text("Eirene update", style="bold"),
                     title_align="left", box=box.ROUNDED, expand=False, padding=(0, 2),
                     border_style="red" if self.failed else "dim")
