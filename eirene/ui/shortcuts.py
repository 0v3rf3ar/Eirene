"""Shared definitions for quick actions and their menu descriptions."""

SHORTCUTS = (
    ("f1", "help_menu", "F1", "Open the command menu"),
    ("ctrl+k", "keybindings", "Ctrl + K", "Show keybindings"),
    ("f2", "pick_model", "F2", "Choose a model"),
    ("f3", "pick_session", "F3", "Switch sessions"),
    ("ctrl+t", "pick_theme", "Ctrl + T", "Choose a theme"),
    ("ctrl+p", "toggle_suggestions", "Ctrl + P", "Toggle prompt suggestions"),
)

EDITING_KEYS = (
    ("shift + tab", "Cycle auto / manual / plan"),
    ("esc", "Close a popup or stop work"),
    ("ctrl + e", "Jump to the latest output"),
    ("ctrl + shift + c", "Copy selected text"),
    ("ctrl + d", "Exit"),
    ("up / down", "Recall prompt history"),
    ("Tab / →", "Copy a suggestion into empty input"),
    ("\\ then enter", "Insert a new line"),
)
