"""Read-only installation and environment diagnostics."""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path

from . import paths
from .config import CONFIG_VERSION, Config
from ..providers import registry as providers
from . import credentials


def collect(config: Config | None = None) -> dict:
    config = config or Config.load()
    home = paths.home()
    provider = config.provider or ""
    configured = []
    for key in config.configured_providers():
        entry = config.provider_config(key)
        configured.append({"name": key, "has_key": bool(config.api_key(key)),
                           "has_url": bool(entry.get("base_url")),
                           "model": str(entry.get("model") or "")})
    scheduler_tools = {name: bool(shutil.which(name)) for name in
                       ("systemctl", "launchctl", "schtasks")}
    writable = _writable(home)
    known = not provider or provider in providers.SPECS
    return {
        "ok": writable and known and config.data.get("version") == CONFIG_VERSION,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "data_home": str(home),
        "data_home_exists": home.is_dir(),
        "data_home_writable": writable,
        "config_version": config.data.get("version"),
        "expected_config_version": CONFIG_VERSION,
        "active_provider": provider,
        "active_provider_known": known,
        "providers": configured,
        "sessions": _count(paths.sessions_dir(), "*.jsonl"),
        "skills": _count(paths.skills_dir(), "*.md"),
        "runtime_log": str(paths.runtime_log()),
        "scheduler_tools": scheduler_tools,
        "execution_isolation": config.get("execution_isolation", "none"),
        "bubblewrap_available": bool(shutil.which("bwrap")),
        "credential_store": config.get("credential_store", "file"),
        "keyring_available": credentials.available(),
    }


def render(report: dict, *, json_output: bool = False) -> str:
    if json_output:
        return json.dumps(report, indent=2, ensure_ascii=False)
    lines = ["eirene diagnostics", f"  Python: {report['python']}",
             f"  Platform: {report['platform']}",
             f"  Data: {report['data_home']}",
             f"  Config schema: {report['config_version']} "
             f"(expected {report['expected_config_version']})",
             f"  Provider: {report['active_provider'] or 'not configured'}",
             f"  Sessions: {report['sessions']}", f"  Skills: {report['skills']}",
             f"  Log: {report['runtime_log']}"]
    if not report["data_home_writable"]:
        lines.append("  WARNING: data directory is not writable")
    if not report["active_provider_known"]:
        lines.append("  WARNING: active provider is unknown")
    lines.append("  Result: " + ("ready" if report["ok"] else "problems found"))
    return "\n".join(lines)


def _count(directory: Path, pattern: str) -> int:
    try:
        return sum(1 for _ in directory.glob(pattern))
    except OSError:
        return 0


def _writable(path: Path) -> bool:
    parent = path if path.exists() else path.parent
    return parent.exists() and os.access(parent, os.W_OK)
