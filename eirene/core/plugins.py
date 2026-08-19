"""Declarative local plugin discovery with no executable Python imports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import paths

MANIFEST_VERSION = 1


@dataclass
class Plugin:
    name: str
    path: Path
    description: str = ""
    skills: list[Path] = field(default_factory=list)
    hooks: dict[str, list[str]] = field(default_factory=dict)
    mcp_servers: dict[str, dict[str, Any]] = field(default_factory=dict)


def discover() -> list[Plugin]:
    found = []
    directory = paths.plugins_dir()
    if not directory.exists():
        return found
    for manifest in sorted(directory.glob("*/plugin.json")):
        try:
            body = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(body, dict) or int(body.get("version", 1)) != MANIFEST_VERSION:
                continue
            name = str(body.get("name") or manifest.parent.name).strip()
            if not name:
                continue
            skills = []
            for raw in body.get("skills", []):
                candidate = (manifest.parent / str(raw)).resolve()
                if manifest.parent.resolve() in candidate.parents and candidate.is_file() \
                        and candidate.suffix == ".md":
                    skills.append(candidate)
            hooks = _hooks(body.get("hooks"))
            servers = body.get("mcp_servers") if isinstance(body.get("mcp_servers"), dict) else {}
            found.append(Plugin(name, manifest.parent,
                                str(body.get("description") or ""), skills, hooks,
                                {str(k): v for k, v in servers.items() if isinstance(v, dict)}))
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return found


def skill_paths() -> list[Path]:
    return [path for plugin in discover() for path in plugin.skills]


def merged_hooks(config) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {"before_tool": [], "after_tool": []}
    configured = config.get("hooks", {})
    if isinstance(configured, dict):
        for event in merged:
            value = configured.get(event, [])
            if isinstance(value, list):
                merged[event].extend(str(command) for command in value if str(command).strip())
    for plugin in discover():
        if not config.plugin_enabled(plugin.name):
            continue
        for event in merged:
            merged[event].extend(plugin.hooks.get(event, []))
    return merged


def merged_mcp_servers(config) -> dict[str, dict[str, Any]]:
    servers = config.get("mcp_servers", {})
    merged = dict(servers) if isinstance(servers, dict) else {}
    for plugin in discover():
        if config.plugin_enabled(plugin.name):
            for name, definition in plugin.mcp_servers.items():
                merged.setdefault(name, definition)
    return merged


def _hooks(raw) -> dict[str, list[str]]:
    result = {"before_tool": [], "after_tool": []}
    if not isinstance(raw, dict):
        return result
    for event in result:
        values = raw.get(event, [])
        if isinstance(values, list):
            result[event] = [str(value) for value in values if str(value).strip()]
    return result
