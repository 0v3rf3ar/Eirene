"""Open the user config file in the preferred editor."""

from __future__ import annotations

import asyncio
import os
import shlex
import shutil
import subprocess
import sys

from textual.app import SuspendNotSupported

from ..core import paths
from ..core.errors import CommandError
from ..core.subprocesses import external_environment
from . import register

IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"

# Editors that run inside the terminal, best first.
TERMINAL_EDITORS = ("nvim", "vim", "vi")


def _detached(command: list[str]) -> None:
    """Launch a program detached so Eirene keeps control of the terminal."""
    subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, env=external_environment())


def _default_editor() -> list[str]:
    """The OS default editor when nvim/vim are absent."""
    for var in ("VISUAL", "EDITOR"):
        value = os.environ.get(var)
        if value:
            return shlex.split(value)
    for name in ("editor", "nano"):
        if shutil.which(name):
            return [name]
    return []


def _resolve_editor(configured: str) -> list[str]:
    """Resolve the editor, best first: config, then nvim, then vim, then the
    platform default (notepad on Windows; $VISUAL/$EDITOR elsewhere)."""
    if configured:
        argv = shlex.split(configured)
        if shutil.which(argv[0]):
            return argv
    for name in TERMINAL_EDITORS:
        if shutil.which(name):
            return [name]
    if IS_WINDOWS:
        return ["notepad"]
    if IS_MAC:
        if shutil.which("open"):
            return ["open", "-t"]
    return _default_editor()


def _is_gui(editor: list[str]) -> bool:
    """Whether the chosen program runs detached rather than in-terminal."""
    name = os.path.basename(editor[0]).lower()
    if name in {"notepad", "code", "atom", "subl", "sublime_text",
                "gedit", "kate", "pluma"}:
        return True
    if IS_WINDOWS and name.removesuffix(".exe") not in {"nvim", "vim", "vi"}:
        return True
    if IS_MAC and name == "open":
        return True
    return False


@register("config", "open the user config file in your preferred editor", "/config")
async def run(app, args: str) -> None:
    config_path = str(paths.config_file())
    configured = str(app.config.get("editor", "") or "").strip()
    editor = _resolve_editor(configured)

    if not editor:
        raise CommandError(
            f"no editor found; set the 'editor' config value or $EDITOR, "
            f"or open {config_path} manually")

    # First run: record the resolved editor so it can be changed later.
    if not configured and not hasattr(app, "_editor_recorded"):
        app._editor_recorded = True
        app.config.set("editor", shlex.join(editor))
        app._save_config()

    if _is_gui(editor):
        await asyncio.to_thread(_detached, editor + [config_path])
        app.say(f"Opened {config_path} in {editor[0]}. Restart Eirene after saving; "
                "settings changed meanwhile could overwrite your edits.")
        return

    app.say(f"Opening {config_path} in {editor[0]}; close it to return to Eirene.")
    try:
        # Block here: the app must not redraw while its terminal writer is stopped.
        with app.suspend():
            subprocess.run(editor + [config_path], env=external_environment())
    except SuspendNotSupported:
        # Headless/Textual Web: no terminal to suspend; open detached instead.
        await asyncio.to_thread(_detached, editor + [config_path])
        app.say(f"Opened {config_path} in {editor[0]}. Restart Eirene after saving.")
        return
    except OSError as exc:
        raise CommandError(f"could not open {config_path}: {exc}")
    # Load the edits now, so a later save cannot overwrite them with stale settings.
    problem = app.config.reload()
    if problem:
        app.say(f"{problem}; your edits were not applied. Run /config to fix the file.", "warn")
    else:
        app.say("Reloaded your settings; some take effect on the next turn.")
