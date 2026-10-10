"""Adaptive budgets for local Ollama models."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from ..core.prompt import TOOL_APPROVAL_GUIDANCE


COMPACT_TOOLS = {
    "request_full_access",
    "ask_user", "read_file", "list_dir", "glob", "search_text",
    "write_file", "edit_file", "apply_patch", "run_command", "web_search", "web_fetch",
    "read_output", "start_process", "poll_process", "stop_process", "list_processes",
}
PLUGIN_TOOLS = {"load_skill", "load_plugin_resource", "delegate_tasks", "plan_show", "plan_update", "plan_set_status"}
BALANCED_TOOLS = COMPACT_TOOLS | {
    "read_image", "project_info",
    "language_diagnostics", "find_symbol", "find_references",
}


@dataclass
class LocalProfile:
    """A conservative model/hardware-specific agent budget."""

    tier: str
    parameters_b: float | None
    ram_gb: float
    cpu_threads: int
    gpu_vram_gb: float

    @classmethod
    def detect(cls, model: str = "") -> "LocalProfile":
        params = parameter_billions(model)
        ram = _ram_gb()
        threads = os.cpu_count() or 1
        vram = _gpu_vram_gb()
        if ((params is None and not vram) or ram < 12 or threads <= 2
                or (params is not None and params <= 4.5)):
            tier = "compact"
        elif params is not None and params <= 10:
            tier = "balanced"
        elif vram < 8 or ram < 24:
            tier = "balanced"
        else:
            tier = "full"
        return cls(tier, params, ram, threads, vram)

    def with_model(self, model: str, details: dict | None = None) -> "LocalProfile":
        params = _details_parameters(details or {}) or parameter_billions(model)
        label = f"{params:g}b" if params is not None else model
        return self.detect(label)

    @property
    def max_tokens(self) -> int:
        return {"compact": 1024, "balanced": 4096, "full": 16384}[self.tier]

    @property
    def max_iterations(self) -> int:
        return {"compact": 5, "balanced": 12, "full": 40}[self.tier]

    @property
    def context_tokens(self) -> int:
        return {"compact": 4096, "balanced": 8192, "full": 32768}[self.tier]

    def tools(self, specs: list[dict] | None) -> list[dict] | None:
        if not specs or self.tier == "full":
            return specs
        allowed = set(COMPACT_TOOLS if self.tier == "compact" else BALANCED_TOOLS)
        if any(spec.get("name") in {"load_plugin_resource", "delegate_tasks"} for spec in specs):
            allowed |= PLUGIN_TOOLS
        else:
            # The host only sends load_skill when an enabled skill exists.
            allowed.add("load_skill")
        selected = [spec for spec in specs if spec.get("name") in allowed
                    or str(spec.get("name", "")).startswith("mcp__")]
        return selected or None

    def system(self, original: str) -> str:
        if self.tier == "full":
            return original
        sandbox = _field(original, "Sandbox")
        mode_match = re.search(r"^Mode is\s+(.+)$", original, re.MULTILINE)
        mode = mode_match.group(1).strip().rstrip(".") if mode_match else "unknown"
        host = _field(original, "OS")
        commands = (
            "powershell=true: Get-Content -LiteralPath 'file' -TotalCount 40 or -Tail 40; "
            "Select-String | Select-Object -First 20 Path,LineNumber,Line."
            if "windows" in host.lower() else
            "POSIX: sed -n '10,50p' 'file'; tail -n 40 'log'; "
            "rg -n -I -m 20 --max-columns 200 'pattern' 'src/file'. -m is per file."
        )
        selected = _field(original, "Bounded read commands")
        if selected != "unknown":
            commands = selected
        facts = ""
        for label in ("Environment preflight", "Hardware", "Host tools"):
            value = _field(original, label)
            if value != "unknown":
                facts += f"{label}: {value[:240] if label == 'Environment preflight' else value[:160]}\n"
        access = _field(original, "Permissions")
        policy = ("Full access: host files/network/commands allowed; OS privileges apply; manual still asks before changes and commands."
                  if access.startswith("full-access") and mode != "plan" else
                  "Sandboxed: host approval or request_full_access grants access for this response; plan: reads only.")
        base = f"""You are Eirene. Use tools; be concise.
Sandbox: {sandbox}
OS: {host}
Mode: {mode}
{facts}{policy}
{TOOL_APPROVAL_GUIDANCE}
Use preflight facts first; check unknown tools with bounded read-only probes. Never guess a package manager.
Use focused file/search tools; don't repeat calls.
Reads: pattern/context, tail, offset/limit, byte_offset.
Quote paths; retain errors and exit status.
Set timeout: 30 reads, 300 tests, 600 builds; no interactive commands.
{commands}
Partial output is incomplete. read_output limit=1024; next_offset as offset.
Search literal text or filenames; batch reads.
poll_process wait=true when idle; never restart a running command.
Research: web_search; use passages; cite URLs.
"""
        if self.tier == "balanced":
            base += ("Prefer targeted reads and searches. Batch independent work. "
                     "After edits, run the narrowest useful verification. Ask through "
                     "ask_user only when a decision is essential.\n")
        # Shorten generic host prose, never discard the user's active command,
        # enabled skill routes, agent profiles or MCP instructions.
        markers = ("Available skills (", "Current command instructions:",
                   "Plugin lifecycle instructions (", "Plugin host tools:", "MCP server instructions:")
        matches = [original.find(marker) for marker in markers if marker in original]
        if matches:
            base += "\n" + original[min(matches):].strip()
        return base

    @property
    def description(self) -> str:
        size = f", {self.parameters_b:g}B" if self.parameters_b is not None else ""
        gpu = f", {self.gpu_vram_gb:.0f}GB VRAM" if self.gpu_vram_gb else ", CPU"
        return f"{self.tier}{size}{gpu}, {self.ram_gb:.0f}GB RAM"


def parameter_billions(model: str) -> float | None:
    matches = re.findall(r"(?:^|[:_-])(\d+(?:\.\d+)?)b(?:$|[:_-])", model.lower())
    return float(matches[-1]) if matches else None


def _details_parameters(details: dict) -> float | None:
    value = str(details.get("parameter_size") or "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*[bB]", value)
    return float(match.group(1)) if match else None


def _ram_gb() -> float:
    # Linux exposes the clearest value here and containers may deliberately
    # present a constrained total, so prefer it when available.
    try:
        text = Path("/proc/meminfo").read_text(encoding="utf-8")
        match = re.search(r"^MemTotal:\s+(\d+)\s+kB", text, re.MULTILINE)
        if match:
            return int(match.group(1)) / 1024 / 1024
    except OSError:
        pass
    # macOS and other POSIX systems expose physical pages through sysconf.
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        if pages > 0 and page_size > 0:
            return pages * page_size / 1024 ** 3
    except (AttributeError, OSError, TypeError, ValueError):
        pass
    # Windows has no os.sysconf; GlobalMemoryStatusEx is available from XP on.
    if os.name == "nt":
        try:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total_physical", ctypes.c_ulonglong),
                            ("available_physical", ctypes.c_ulonglong),
                            ("total_page_file", ctypes.c_ulonglong),
                            ("available_page_file", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong),
                            ("available_virtual", ctypes.c_ulonglong),
                            ("available_extended_virtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.length = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return status.total_physical / 1024 ** 3
        except (AttributeError, OSError, ValueError):
            pass
    return 8.0


def _gpu_vram_gb() -> float:
    totals = []
    for path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            totals.append(int(path.read_text().strip()))
        except (OSError, ValueError):
            pass
    if totals:
        return max(totals) / 1024 ** 3
    # NVIDIA does not expose VRAM through a stable text file. Presence is enough
    # to avoid calling an external probe; use a conservative mid-range estimate.
    if Path("/proc/driver/nvidia/gpus").exists():
        return 8.0
    # Apple Silicon uses unified memory rather than dedicated VRAM. Treat half
    # of physical RAM as the conservative usable graphics/model budget.
    if sys.platform == "darwin" and platform_machine() == "arm64":
        return _ram_gb() / 2
    return 0.0


def platform_machine() -> str:
    """Small seam for platform tests without importing a heavyweight probe."""
    import platform
    return platform.machine().lower()


def _field(text: str, name: str) -> str:
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else "unknown"
