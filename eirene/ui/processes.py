"""Background commands directly below the model line; idle costs no timer."""

from __future__ import annotations

import time
from rich.text import Text
from textual import events
from textual.widgets import Static
from ..tools import activity, processes, shell
from .format import strip_escapes


class ProcessBar(Static):
    DEFAULT_CSS = """
    ProcessBar { width: 1fr; height: 1; padding: 0 1; background: transparent; display: none; }
    ProcessBar:focus { text-style: bold; }
    """
    can_focus = True
    BINDINGS = [("enter", "manage", "View/stop commands")]

    def __init__(self):
        super().__init__(Text(""))
        self._timer = None

    def on_mount(self):
        activity.subscribe(self.refresh_state)
        self.refresh_state()

    def on_unmount(self):
        activity.unsubscribe(self.refresh_state)
        if self._timer:
            self._timer.stop()

    @staticmethod
    def _rows():
        return processes.running()

    def refresh_state(self):
        rows = self._rows()
        self.display = bool(rows)
        if not rows:
            if self._timer:
                self._timer.stop()
                self._timer = None
            self.update(Text(""))
            return
        if self._timer is None and self.is_mounted:
            self._timer = self.set_interval(1, self.refresh_state)
        labels = []
        for _, process_id in rows[:2]:
            item = processes._get(process_id)
            elapsed = time.monotonic() - item.started
            command = " ".join(strip_escapes(item.command).split())[:48]
            deadline = (
                f" / {item.deadline - item.started:.0f}s" if item.deadline else ""
            )
            labels.append(f"{command} {elapsed:.0f}s{deadline}")
        extra = f" · +{len(rows) - 2} more" if len(rows) > 2 else ""
        self.update(
            Text(
                f"● {len(rows)} background · "
                + " · ".join(labels)
                + extra
                + " · view/stop",
                overflow="ellipsis",
                no_wrap=True,
            )
        )

    def on_click(self, event: events.Click):
        event.stop()
        self.action_manage()

    def action_manage(self):
        self.run_worker(self._show_commands(), group="process-bar", exclusive=True)

    async def _show_commands(self):
        rows = self._rows()
        options = []
        for label, value in rows:
            options += [
                (f"view:{value}", label, "View output"),
                (f"stop:{value}", label, "Stop command"),
            ]
        options += [
            (f"provider:{value}", label, "Stop provider command")
            for label, value in activity.provider_commands()
        ]
        options += [
            (f"foreground:{value}", label, "Stop foreground command")
            for label, value in shell.active()
        ]
        if not options:
            self.app.say("no running commands")
            return
        choice = await self.app.ask_choice(
            "background commands — view output or stop", options
        )
        if choice:
            action, _, value = choice.partition(":")
            if action == "provider":
                self.app.say(await activity.stop_provider_command(value))
            elif action == "foreground":
                self.app.say(await shell.stop_active(value))
            elif action == "stop":
                self.app.say(await processes.stop(value))
            else:
                from .output import OutputScreen

                self.app.push_screen(OutputScreen(ProcessOutput(processes._get(value))))
        self.refresh_state()


class ProcessOutput:
    """Live adapter for the existing output viewer."""

    def __init__(self, item):
        self.item = item

    @property
    def label(self):
        return self.item.command

    @property
    def artifact_id(self):
        return self.item.artifact.id if self.item.artifact else ""

    @property
    def finished(self):
        return not self.item.running

    @property
    def is_error(self):
        return self.item.state not in {"running", "starting", "succeeded"}

    @property
    def seconds(self):
        return time.monotonic() - self.item.started

    @property
    def output(self):
        return self.item.capture.text()

    @property
    def result(self):
        return self.output
