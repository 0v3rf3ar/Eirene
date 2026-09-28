"""Small cross-platform helpers for launching command-line programs."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def executable_argv(executable: str, *args: str) -> list[str]:
    """Return argv that can launch native executables and Windows batch shims.

    npm-installed CLIs are commonly exposed as ``.cmd`` files on Windows.
    CreateProcess (and therefore asyncio's exec API) cannot execute those files
    directly, so route only batch shims through the system command processor.
    """
    argv = [executable, *args]
    if not IS_WINDOWS or Path(executable).suffix.lower() not in (".bat", ".cmd"):
        return argv
    command_processor = os.environ.get("COMSPEC", "cmd.exe")
    return [command_processor, "/d", "/s", "/c", '"' + subprocess.list2cmdline(argv) + '"']
