"""Shared definitions for quick actions and their menu descriptions."""

import sys

# Copy follows the platform's own terminal shortcut; the others stay inert so
# Textual's built-in ctrl+c / super+c copy cannot fire behind it. Terminals
# without the kitty keyboard protocol (VTE, xterm) send ctrl+shift+c as a plain
# ctrl+c, so on Linux both spellings mean copy.
if sys.platform == "win32":
    COPY_KEYS, COPY_LABEL = ("ctrl+c",), "ctrl + c"
elif sys.platform == "darwin":
    COPY_KEYS, COPY_LABEL = ("super+c",), "cmd + c"
else:
    COPY_KEYS, COPY_LABEL = ("ctrl+shift+c", "ctrl+c"), "ctrl + shift + c"
INERT_COPY_KEYS = tuple(key for key in ("ctrl+c", "super+c") if key not in COPY_KEYS)

SHORTCUTS = (
    ("f1", "help_menu", "F1", "Open the command menu"),
    ("ctrl+k", "keybindings", "Ctrl + K", "Show keybindings"),
    ("ctrl+b", "manage_processes", "Ctrl + B", "View or stop running commands"),
    ("f2", "pick_model", "F2", "Choose a model"),
    ("f3", "pick_session", "F3", "Switch sessions"),
    ("ctrl+t", "pick_theme", "Ctrl + T", "Choose a theme"),
    ("ctrl+p", "toggle_suggestions", "Ctrl + P", "Toggle prompt suggestions"),
)

EDITING_KEYS = (
    ("shift + tab", "Cycle auto / manual / plan"),
    ("esc", "Close a popup or stop work"),
    ("ctrl + e", "Jump to the latest output"),
    (COPY_LABEL, "Copy selected text"),
    ("ctrl + d", "Exit"),
    ("up / down", "Recall prompt history"),
    ("Tab / →", "Copy a suggestion into empty input"),
    ("\\ then enter", "Insert a new line"),
)
