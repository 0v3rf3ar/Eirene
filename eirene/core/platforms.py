"""Host-specific command contracts shared by every model provider."""
from __future__ import annotations
import os
import platform
from pathlib import Path


def shell_name() -> str:
    if os.name == "nt":
        return "cmd (PowerShell available through powershell=true)"
    return "bash" if Path("/bin/bash").is_file() else "sh"


def guidance(*, native: bool = False, system: str | None = None) -> str:
    system = system or platform.system()
    common = "Use the host's command syntax; never assume GNU utilities, Bash, or Unix paths exist. Prefer portable file/search tools for reading and editing. Check executable availability before using optional programs."
    if system == "Windows":
        selector = ("Select the appropriate shell with your native command tool." if native else
                    "run_command and start_process default to cmd; set powershell=true for PowerShell.")
        detail = fr"""Windows command profile. {selector}
CMD: dir /b, type "file", where program, set "NAME=value", %NAME%, and && for success chaining. Single quotes do not quote CMD arguments. Quote paths with double quotes.
PowerShell: Get-ChildItem -LiteralPath '.', Get-Content -LiteralPath 'file' -TotalCount 80, Select-String, Get-Command, $env:NAME='value'. Use & 'C:\Program Files\tool.exe' for quoted executable paths. Windows PowerShell 5.1 has no &&; check $LASTEXITCODE for native programs. Use -LiteralPath for filenames containing brackets.
Use python or py -3 when installed, not an assumed python3 alias. Use ping -n 4; no /dev/null, sudo, chmod, sed, or Unix environment assignments. PTY mode is unavailable in Eirene on Windows.
Native commands require individual approval because Eirene has no Windows kernel isolation backend. In plan mode use portable read/search tools instead."""
    elif system == "Darwin":
        detail = """macOS command profile: Eirene uses /bin/bash (or /bin/sh), not the interactive login shell. Use POSIX syntax and BSD utilities. Built-in Bash may be 3.2: avoid associative arrays/mapfile. sed -i requires a backup suffix (sed -i '' ...); prefer edit_file. stat uses -f, date uses -v; GNU readlink -f, timeout, and grep -P may be absent. Use command -v, printf, head/tail, and python3 if installed. Both Intel and Apple Silicon paths must be discovered, not hardcoded."""
    else:
        detail = "Linux command profile: use POSIX/Bash syntax, command -v, head/tail, and bounded searches. Use ping -c 4 and sudo -n. Kernel command isolation uses Bubblewrap."
    if native:
        detail = detail.replace("prefer edit_file", "prefer native file editing tools")
        detail = detail.split("Native commands require individual approval")[0]
    return common + "\n" + detail
