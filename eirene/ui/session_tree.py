"""Interactive saved-session hierarchy in a draggable popup."""
from rich.text import Text
from textual.screen import ModalScreen
from textual.widgets import Static, Tree
from .window import DraggableWindow


class SessionTreeScreen(ModalScreen[str | None]):
    DEFAULT_CSS = '''
    SessionTreeScreen { align: center middle; }
    SessionTreeScreen > DraggableWindow {
        width: 85%; max-width: 115; height: 80%;
        border: round $primary; background: $surface; padding: 1;
    }
    SessionTreeScreen Tree { height: 1fr; background: $surface; }
    SessionTreeScreen Static { height: auto; }
    SessionTreeScreen #session-tree-details { margin-top: 1; color: $text-muted; }
    '''
    BINDINGS = [('m', 'mother', 'Mother session'), ('left', 'collapse', 'Collapse'),
                ('right', 'expand', 'Expand')]

    def __init__(self, rows, current, allow_switch=True):
        super().__init__()
        self.rows, self.current, self.allow_switch = rows, current, allow_switch
        self.nodes = {}

    def compose(self):
        with DraggableWindow():
            yield Static('Session hierarchy', markup=False)
            yield Tree('Mother session', id='session-tree')
            yield Static('', id='session-tree-details', markup=False)
            yield Static('↑/↓ browse · ←/→ expand · Enter open · M mother · Esc close', markup=False)

    def on_mount(self):
        tree = self.query_one(Tree)
        tree.guide_depth = 4
        stack = []
        for info, depth in self.rows:
            label = info['agent'] or info['name']
            label += ' (mother session)' if depth == 0 else ''
            label += ' (current)' if info['id'] == self.current else ''
            label += f"  [{info['status']}]"
            if depth == 0:
                node = tree.root
                node.set_label(Text(label))
                node.data = info
            else:
                node = stack[depth - 1].add(Text(label), data=info, expand=True)
            stack[depth:] = [node]
            self.nodes[info['id']] = node
        tree.root.expand_all()
        tree.move_cursor(self.nodes.get(self.current, tree.root))
        tree.focus()

    def on_tree_node_highlighted(self, event):
        info = event.node.data
        if info:
            message = f"{info['name']}\n{info['id']} · {info['status']}"
            if not self.allow_switch:
                message += '\nFinish or stop the active turn before switching sessions.'
            self.query_one('#session-tree-details', Static).update(message)

    def on_tree_node_selected(self, event):
        if self.allow_switch and event.node.data:
            self.dismiss(event.node.data['id'])

    def action_mother(self):
        if self.allow_switch:
            self.dismiss(self.rows[0][0]['id'])
        else:
            self.query_one(Tree).move_cursor(self.query_one(Tree).root)

    def action_collapse(self):
        node = self.query_one(Tree).cursor_node
        if node:
            if node.is_expanded:
                node.collapse()
            elif node.parent:
                self.query_one(Tree).move_cursor(node.parent)

    def action_expand(self):
        node = self.query_one(Tree).cursor_node
        if node:
            node.expand()
