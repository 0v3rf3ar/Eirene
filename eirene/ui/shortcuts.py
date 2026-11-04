"""Shared definitions for quick actions and their menu descriptions."""

import sys

# Ctrl+C and Ctrl+Shift+C both copy everywhere (plus Cmd+C on macOS), so the
# same keys work locally and over SSH whatever the user's own computer is.
# Terminals without the kitty keyboard protocol (VTE, xterm) send ctrl+shift+c
# as a plain ctrl+c anyway. The rest stay inert so Textual's built-in copy
# cannot fire behind them.
if sys.platform == "darwin":
    COPY_KEYS, COPY_LABEL = ("super+c", "ctrl+c", "ctrl+shift+c"), "cmd + c / ctrl + c"
else:
    COPY_KEYS, COPY_LABEL = ("ctrl+c", "ctrl+shift+c"), "ctrl + c / ctrl + shift + c"
INERT_COPY_KEYS = tuple(key for key in ("ctrl+c", "super+c") if key not in COPY_KEYS)

SHORTCUTS = (
    ("f1", "help_menu", "F1", "Open the command menu"),
    ("ctrl+k", "keybindings", "Ctrl + K", "Show keybindings"),
    ("ctrl+b", "manage_processes", "Ctrl + B", "View or stop running commands"),
    ("f2", "pick_model", "F2", "Choose a model"),
    ("f3", "pick_session", "F3", "Switch sessions"),
    ("f4", "toggle_mouse", "F4", "Switch mouse: Eirene or terminal selection"),
    ("ctrl+t", "pick_theme", "Ctrl + T", "Choose a theme"),
    ("ctrl+p", "toggle_suggestions", "Ctrl + P", "Toggle prompt suggestions"),
)

EDITING_KEYS = (
    ("shift + tab", "Cycle auto / manual / plan"),
    ("esc", "Close a popup or stop work"),
    ("ctrl + e", "Jump to the latest output"),
    (COPY_LABEL, "Copy selected text"),
    ("ctrl + v / alt + v", "Paste a picture from the clipboard as a file"),
    ("ctrl + d", "Exit"),
    ("up / down", "Recall prompt history"),
    ("Tab / →", "Copy a suggestion into empty input"),
    ("\\ then enter", "Insert a new line"),
)
