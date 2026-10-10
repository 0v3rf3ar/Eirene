"""Workspace trust gate shown before the interactive agent is initialized."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from ..core.text import safe_text
from .backdrop import LogoBackdrop as TrustBackdrop
from .picker import Picker
from .theme import PLAIN


class WorkspaceTrust(App[bool]):
    """Require an explicit choice to trust the workspace for this process."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "eirene — workspace trust"
    CSS = """
    Screen { background: transparent; layers: watermark content; }
    #trust-explanation { layer: content; height: auto; padding: 1; }
    Picker { layer: content; }
    """
    BINDINGS = [
        Binding("ctrl+c,ctrl+d", "decline", "leave", priority=True, show=False),
    ]

    def __init__(self, workspace: Path):
        super().__init__()
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        yield TrustBackdrop()
        body = Text("Trust this workspace?\n\n", style="bold")
        body.append(safe_text(str(self.workspace)) + "\n\n", style="bold")
        body.append(
            "Eirene can read and edit files and run commands here. "
            "Only continue if you trust this workspace.", style="dim")
        yield Static(body, id="trust-explanation")
        yield Picker(show_detail=False)

    def on_mount(self) -> None:
        self.register_theme(PLAIN)
        self.theme = "eirene"
        self.run_worker(self._ask(), exclusive=True)

    async def _ask(self) -> None:
        answer = await self.query_one(Picker).choose(
            "Continue?",
            [("trust", "Yes, trust this workspace", "continue"),
             ("leave", "No, exit Eirene", "")],
            selected="trust")
        self.exit(answer == "trust")

    def action_decline(self) -> None:
        self.exit(False)


def confirm_workspace_trust(workspace: Path) -> bool:
    """Only an explicit trust choice permits startup; cancellation denies it."""
    return WorkspaceTrust(workspace).run() is True
