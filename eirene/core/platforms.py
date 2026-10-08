"""Host-specific command contracts shared by every model provider."""
from __future__ import annotations
import os
import platform
from pathlib import Path
from dataclasses import dataclass
import shutil


def shell_name() -> str:
    if os.name == "nt":
        return "PowerShell (powershell=true; shell=cmd for batch syntax)"
    return "bash" if Path("/bin/bash").is_file() else "sh"


def guidance(*, native: bool = False, system: str | None = None, host=None) -> str:
    system = system or platform.system()
    common = "Use the host's command syntax; never assume GNU utilities, Bash, or Unix paths exist. Use native-backed file/search tools for precise bounded reads; use edit tools for changes. Use the detected tool inventory; check availability only for additional optional programs."
    if system == "Windows":
        selector = ("Select the appropriate shell with your native command tool." if native else
                    "run_command and start_process prefer PowerShell; use shell=cmd for CMD syntax (powershell=true remains supported).")
        detail = fr"""Windows command profile. {selector}
CMD: dir /b, type "file", where program, set "NAME=value", %NAME%, and && for success chaining. Single quotes do not quote CMD arguments. Quote paths with double quotes.
PowerShell: Get-ChildItem -LiteralPath '.', Get-Content -LiteralPath 'file' -TotalCount 80, Select-String, Get-Command, $env:NAME='value'. Use & 'C:\Program Files\tool.exe' for quoted executable paths. Windows PowerShell 5.1 has no &&; check $LASTEXITCODE for native programs. Use -LiteralPath for filenames containing brackets.
Use python or py -3 when installed, not an assumed python3 alias. Use ping -n 4; no /dev/null, sudo, chmod, sed, or Unix environment assignments. PTY mode is unavailable in Eirene on Windows.
Native commands require individual approval because Eirene has no Windows kernel isolation backend. In plan mode use the fixed native read/search tools."""
        if host is not None and not ({"pwsh", "powershell"} & set(host.available)):
            detail = ("Windows command profile: CMD only; PowerShell was not found on host PATH. "
                      "Use dir /b, where program, set \"NAME=value\", %NAME%, and && for success chaining. "
                      "Quote paths with double quotes; use native read/search tools for bounded reads. "
                      "Use ping -n 4. PTY mode is unavailable. "
                      "Native commands require individual approval; plan mode uses fixed native read tools.")
    elif system == "Darwin":
        detail = """macOS command profile: Eirene uses /bin/bash (or /bin/sh), not the interactive login shell. Use POSIX syntax and BSD utilities. Built-in Bash may be 3.2: avoid associative arrays/mapfile. sed -i requires a backup suffix (sed -i '' ...); prefer edit_file. stat uses -f, date uses -v; GNU readlink -f, timeout, and grep -P may be absent. Use command -v, printf, head/tail, and python3 if installed. Both Intel and Apple Silicon paths must be discovered, not hardcoded."""
    else:
        detail = "Linux command profile: use POSIX/Bash syntax, command -v, head/tail, and bounded searches. Use ping -c 4 and sudo -n. Kernel command isolation uses Bubblewrap."
    if native:
        common = common.replace("Use the detected tool inventory; check availability only for additional optional programs.",
                                "Check executable availability before using optional programs.")
        detail = detail.replace("prefer edit_file", "prefer native file editing tools")
        detail = detail.split("Native commands require individual approval")[0]
    return common + "\n" + detail


@dataclass(frozen=True)
class Host:
    """Startup facts collected locally, without asking a model or running commands."""

    system: str
    shell: str
    architecture: str
    cpu_threads: int
    ram_gb: float
    gpu_memory_gb: float
    available: tuple[str, ...]
    missing: tuple[str, ...]

    @classmethod
    def detect(cls) -> "Host":
        from ..providers.local_profile import _ram_gb, _gpu_vram_gb
        system = platform.system()
        candidates = ("git", "rg", "node", "npm", "pytest", "cargo", "go")
        candidates += (("pwsh", "powershell", "python", "py") if system == "Windows"
                       else ("python3", "find", "awk", "grep", "sed", "head", "tail", "base64", "make"))
        installed = tuple(name for name in candidates if shutil.which(name))
        selected_shell = ("PowerShell (powershell=true; shell=cmd for batch syntax)"
                          if system == "Windows" and {"pwsh", "powershell"} & set(installed)
                          else "cmd" if system == "Windows" else shell_name())
        return cls(system, selected_shell, platform.machine() or "unknown",
                   os.cpu_count() or 1, _ram_gb(), _gpu_vram_gb(), installed,
                   tuple(name for name in candidates if name not in installed))

    def hardware_line(self) -> str:
        gpu = f"~{self.gpu_memory_gb:g} GiB" if self.gpu_memory_gb else "unknown"
        return (f"Hardware: {self.architecture}, {self.cpu_threads} CPU threads, "
                f"~{self.ram_gb:.0f} GiB RAM; GPU/model memory estimate {gpu}")

    def tools_line(self) -> str:
        return "Host tools: " + (", ".join(self.available) or "none detected")

    def prompt_block(self) -> str:
        return (self.hardware_line() + "\n" + self.tools_line() +
                "\nAbsent from host PATH: " + (", ".join(self.missing) or "none") +
                "\nThis startup inventory is already checked. Use native read/search tools "
                "when a utility is absent; project-installed tools may differ. "
                "Host installation does not imply sandbox access.")

    def read_commands(self) -> str:
        """Only examples for this host, selected from installed utilities."""
        available = set(self.available)
        if self.system == "Windows":
            if available & {"pwsh", "powershell"}:
                return ("powershell=true: Get-Content -LiteralPath 'file' -TotalCount 40; "
                        "Select-String | Select-Object -First 20 Path,LineNumber,Line.")
            return "CMD: dir /b; use read_file/search_text for bounded contents and matches."
        parts = []
        if "sed" in available:
            parts.append("sed -n '10,50p' 'file'")
        if "tail" in available:
            parts.append("tail -n 40 'log'")
        if "rg" in available:
            parts.append("rg -n -I -m 20 --max-columns 200 'pattern' 'src/file' (-m is per file)")
        elif "grep" in available:
            parts.append("grep -n -m 20 'pattern' 'file'")
        return "; ".join(parts) or "Use read_file/search_text for bounded contents and matches."


    def tool_specs(self, specs: list[dict]) -> list[dict]:
        """Remove unavailable shell options without mutating shared schemas."""
        from copy import deepcopy
        result = []
        for spec in specs:
            if spec["name"] in {"run_command", "start_process"}:
                spec = deepcopy(spec)
                properties = spec["parameters"]["properties"]
                if self.system != "Windows" or not {"pwsh", "powershell"} & set(self.available):
                    properties.pop("powershell", None)
                if self.system == "Windows":
                    properties.pop("pty", None)
                    choices = ["auto", "cmd"]
                    if {"pwsh", "powershell"} & set(self.available):
                        choices.append("powershell")
                else:
                    choices = ["auto", "bash", "sh"]
                properties["shell"]["enum"] = choices
            result.append(spec)
        return result
