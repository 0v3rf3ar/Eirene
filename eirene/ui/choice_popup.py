"""Floating searchable choices with a scrollable description."""
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from .picker import Picker
from .window import DraggableWindow


class ChoicePopup(ModalScreen[str | None]):
    DEFAULT_CSS = '''
    ChoicePopup { align: center middle; }
    ChoicePopup > DraggableWindow {
        width: 85%; max-width: 110; height: 80%;
        border: round $primary; background: $surface; padding: 1;
    }
    ChoicePopup Picker { margin: 0; border: none; padding: 0; max-height: 65%; overflow-y: auto; }
    ChoicePopup VerticalScroll { height: 1fr; margin-top: 1; border-top: solid $primary; }
    ChoicePopup #choice-description { height: auto; }
    ChoicePopup #choice-help { height: auto; color: $text-muted; }
    '''

    def __init__(self, title, options, selected=''):
        super().__init__()
        self.title_text, self.options, self.selected = title, options, selected

    def compose(self):
        with DraggableWindow():
            yield Picker(show_detail=False, right_hint=True)
            with VerticalScroll():
                yield Static('', id='choice-description', markup=False)
            yield Static('↑/↓ select · Enter choose · type to filter · Esc close', id='choice-help')

    def on_mount(self):
        self.run_worker(self._choose())

    def _highlight(self, key):
        row = next((row for row in self.options if row[0] == key), None)
        self.query_one('#choice-description', Static).update(str(row[3] if len(row) > 3 else row[2]) if row else '')
        self.query_one(VerticalScroll).scroll_home(animate=False)

    async def _choose(self):
        value = await self.query_one(Picker).choose(self.title_text, self.options,
                                                  selected=self.selected, on_highlight=self._highlight)
        self.dismiss(value)
