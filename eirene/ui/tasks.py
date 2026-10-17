"""Compact live checklist above the prompt."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from ..core import plans
from . import theme

MAX_VISIBLE = 7


class TaskList(Static):
    """Render the active durable plan without adding transcript noise."""

    DEFAULT_CSS = """
    TaskList {
        width: 1fr;
        height: auto;
        max-height: 10;
        margin: 1 0 0 0;
        padding: 0 1;
        background: transparent;
        border: round $primary;
        display: none;
    }
    """

    def __init__(self, root: Path, session_id: str = "") -> None:
        super().__init__(Text(""))
        self.root = root
        self.session_id = session_id

    def on_mount(self) -> None:
        self.restyle()

    def restyle(self) -> None:
        """Refresh step colours; the box follows the shared menu styling."""
        self.refresh_plan()

    def refresh_plan(self) -> None:
        plan = plans.load(self.root, self.session_id or None)
        if not plan.steps:
            self.display = False
            self.update(Text(""))
            return
        accent = theme.for_widget(self)
        body = Text()
        icons = {"pending": "○", "in_progress": "→",
                 "completed": "✓", "blocked": "!"}
        visible = plan.steps[:MAX_VISIBLE]
        for index, step in enumerate(visible):
            if index:
                body.append("\n")
            if accent is None:
                style = "strike dim" if step.status == "completed" else (
                    "bold" if step.status == "in_progress" else "dim")
            else:
                colours = {
                    "pending": accent.detail,
                    "in_progress": f"bold {accent.marker}",
                    "completed": f"strike {accent.detail}",
                    "blocked": f"bold {accent.glow or accent.marker}",
                }
                style = colours[step.status]
            body.append(f" {icons[step.status]} {step.text}", style=style)
        hidden = len(plan.steps) - len(visible)
        if hidden:
            body.append(f"\n … {hidden} more", style="dim")
        self.update(body)
        self.display = True
