"""Compact live checklist above the prompt."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from ..core import plans

MAX_VISIBLE = 7


class TaskList(Static):
    """Render the active durable plan without adding transcript noise."""

    DEFAULT_CSS = """
    TaskList {
        width: 1fr;
        height: auto;
        max-height: 8;
        padding: 0 1;
        background: #3b4149;
        color: #f8f8f2;
        display: none;
    }
    """

    def __init__(self, root: Path) -> None:
        super().__init__(Text(""))
        self.root = root

    def refresh_plan(self) -> None:
        plan = plans.load(self.root)
        if not plan.steps:
            self.display = False
            self.update(Text(""))
            return
        body = Text()
        icons = {"pending": "○", "in_progress": "→",
                 "completed": "✓", "blocked": "!"}
        visible = plan.steps[:MAX_VISIBLE]
        for index, step in enumerate(visible):
            if index:
                body.append("\n")
            style = "strike dim" if step.status == "completed" else (
                "bold" if step.status == "in_progress" else "dim")
            body.append(f" {icons[step.status]} {step.text}", style=style)
        hidden = len(plan.steps) - len(visible)
        if hidden:
            body.append(f"\n … {hidden} more", style="dim")
        self.update(body)
        self.display = True
