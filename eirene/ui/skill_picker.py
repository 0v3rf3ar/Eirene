"""Centered skill chooser with a scrollable description."""

from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from .picker import Picker


class SkillPickerScreen(ModalScreen[str | None]):
    DEFAULT_CSS = """
    SkillPickerScreen { align: center middle; }
    SkillPickerScreen > Vertical {
        width: 80%; max-width: 100; height: 80%;
        border: round $primary; background: $surface; padding: 1;
    }
    SkillPickerScreen Picker {
        margin: 0; border: none; padding: 0; max-height: 60%;
        overflow-y: auto;
    }
    SkillPickerScreen VerticalScroll {
        height: 1fr; margin-top: 1; border-top: solid $primary;
    }
    SkillPickerScreen #skill-description { height: auto; }
    SkillPickerScreen #skill-help { height: auto; color: $text-muted; }
    """

    def __init__(self, options: list[tuple], selected: str = "") -> None:
        super().__init__()
        self.options = options
        self.selected = selected

    def compose(self):
        with Vertical():
            yield Picker(show_detail=False, right_hint=True)
            with VerticalScroll():
                yield Static("", id="skill-description", markup=False)
            yield Static("↑/↓ select · Enter toggle · type to filter · Esc close",
                         id="skill-help")

    def on_mount(self) -> None:
        self.run_worker(self._choose())

    def _highlight(self, name: str) -> None:
        row = next((row for row in self.options if row[0] == name), None)
        self.query_one("#skill-description", Static).update(
            str(row[3]) if row and len(row) > 3 else "")
        self.query_one(VerticalScroll).scroll_home(animate=False)

    async def _choose(self) -> None:
        choice = await self.query_one(Picker).choose(
            "toggle a skill", self.options, on_highlight=self._highlight,
            selected=self.selected)
        self.dismiss(choice)
