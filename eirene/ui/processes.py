"""A conditional top bar for managed background commands."""

from __future__ import annotations

from rich.text import Text
from textual import events
from textual.widgets import Static

from ..tools import activity, processes, shell
from . import art

REFRESH_INTERVAL = 0.2


class ProcessBar(Static):
    """Show live commands and open a stop menu when clicked."""

    DEFAULT_CSS = """
    ProcessBar {
        width: 1fr;
        height: 1;
        dock: top;
        padding: 0 1;
        background: $panel;
        display: none;
    }
    ProcessBar.running {
        display: block;
    }
    ProcessBar:hover {
        text-style: bold;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text(""))
        self._ids: tuple[str, ...] = ()

    def on_mount(self) -> None:
        activity.subscribe(self.refresh_state)
        self.refresh_state()
        self.set_interval(REFRESH_INTERVAL, self.refresh_state)

    def on_unmount(self) -> None:
        activity.unsubscribe(self.refresh_state)

    @staticmethod
    def _rows() -> list[tuple[str, str]]:
        foreground = [(label, f"command:{value}") for label, value in shell.active()]
        background = [(label, f"process:{value}")
                      for label, value in processes.running()]
        provider = [(label, f"provider:{value}")
                    for label, value in activity.provider_commands()]
        return foreground + background + provider

    def refresh_state(self) -> None:
        """Match visibility and text to the currently running commands."""
        rows = self._rows()
        ids = tuple(value for _, value in rows)
        if not rows:
            self._ids = ()
            self.remove_class("running")
            self.display = False
            self.update(Text(""))
            return

        self._ids = ids
        self.add_class("running")
        self.display = True
        count = len(rows)
        body = Text()
        body.append(f"{art.icon('bullet')} ", style="bold")
        body.append(f"{count} running command{'' if count == 1 else 's'}", style="bold")
        body.append("  ·  click to view or stop", style="dim")
        self.update(body)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.run_worker(self._show_commands(), group="process-bar", exclusive=True)

    async def _show_commands(self) -> None:
        """Open the live-command picker without blocking the message loop."""
        rows = self._rows()
        if not rows:
            self.refresh_state()
            return
        options = [(value, label, "") for label, value in rows]
        command_id = await self.app.ask_choice(
            "running commands — select one to stop", options)
        if command_id:
            kind, _, value = command_id.partition(":")
            if kind == "command":
                self.app.say(await shell.stop_active(value))
            elif kind == "provider":
                self.app.say(await activity.stop_provider_command(value))
            else:
                self.app.say(await processes.stop(value))
        self.refresh_state()
