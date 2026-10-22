"""Workspace trust gate shown before the interactive agent is initialized."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Static

from ..core import paths
from ..core.config import Config
from ..core.text import safe_text
from .picker import Picker
from .splash import pixel_logo
from .theme import PLAIN


class TrustPortrait(Static):
    """Use the session-loading portrait in the space above the question."""

    DEFAULT_CSS = """
    TrustPortrait {
        height: 1fr;
        min-height: 0;
        content-align: center middle;
        background: transparent;
    }
    """

    def on_resize(self, event: events.Resize) -> None:
        self.update(pixel_logo(max(1, event.size.width - 4),
                               max(1, event.size.height), transparent=True))


class WorkspaceTrust(App[bool]):
    """Ask for permission to remember trust for this workspace path."""

    ENABLE_COMMAND_PALETTE = False
    TITLE = "eirene — workspace trust"
    CSS = """
    Screen { background: transparent; overflow-y: auto; }
    #trust-explanation { height: auto; padding: 1; }
    Picker { margin: 0 0 1 0; }
    """
    BINDINGS = [
        Binding("ctrl+c,ctrl+d", "decline", "leave", priority=True, show=False),
    ]

    def __init__(self, workspace: Path):
        super().__init__()
        self.workspace = workspace

    def compose(self) -> ComposeResult:
        yield TrustPortrait()
        body = Text("Trust this workspace?\n\n", style="bold")
        body.append(safe_text(str(self.workspace)) + "\n\n", style="bold")
        body.append(
            "Eirene can read and edit files and run commands here. "
            "Only continue if you trust this workspace. "
            "Your choice is remembered for this path on future launches.", style="dim")
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
    """Remember explicit trust for an exact resolved workspace path."""
    workspace = workspace.expanduser().resolve()
    paths.ensure_tree()
    config = Config.load()
    trusted = config.get("trusted_workspaces", [])
    if not isinstance(trusted, list):
        trusted = []
    identity = str(workspace)
    if identity in trusted:
        return True
    if WorkspaceTrust(workspace).run() is not True:
        return False
    config.set("trusted_workspaces", [*trusted, identity])
    config.save()
    return True
