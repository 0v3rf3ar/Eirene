"""Small cross-platform helpers for launching command-line programs."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

IS_WINDOWS = os.name == "nt"


def external_environment() -> dict[str, str]:
    """Restore the host loader path for programs outside the frozen bundle."""
    env = dict(os.environ)
    if getattr(sys, "frozen", False):
        for name in ("LD_LIBRARY_PATH", "LIBPATH"):
            original = env.get(name + "_ORIG")
            if original is None:
                env.pop(name, None)
            else:
                env[name] = original
    return env


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
