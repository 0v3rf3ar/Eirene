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
    commands: list[Path] = field(default_factory=list)
    agents: list[Path] = field(default_factory=list)
    lifecycle: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    imported: bool = False
    catalog_shortcut: str = ""


def discover() -> list[Plugin]:
    found = []
    directory = paths.plugins_dir()
    if not directory.exists():
        return found
    manifests = []
    for root in sorted(directory.iterdir()):
        if not root.is_dir() or root.name.startswith("."):
            continue
        manifest = root / ".eirene-plugin.json"
        manifests.append(manifest if manifest.is_file() else root / "plugin.json")
    for manifest in manifests:
        try:
            body = json.loads(manifest.read_text(encoding="utf-8"))
            if not isinstance(body, dict) or int(body.get("version", 1)) != MANIFEST_VERSION:
                continue
            name = str(body.get("name") or manifest.parent.name).strip()
            if not name:
                continue
            def markdown(key):
                result = []
                for raw in body.get(key, []):
                    candidate = (manifest.parent / str(raw)).resolve()
                    if manifest.parent.resolve() in candidate.parents and candidate.is_file() and candidate.suffix == ".md":
                        result.append(candidate)
                return result
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
                                {str(k): v for k, v in servers.items() if isinstance(v, dict)},
                                markdown("commands"), markdown("agents"),
                                body.get("lifecycle", {}), body.get("warnings", []),
                                bool(body.get("imported")), str(body.get("catalog_shortcut", ""))))
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


def available_mcp_servers(config) -> dict[str, dict[str, Any]]:
    """Installed declarations, including servers that have not been enabled."""
    configured = config.get("mcp_servers", {})
    servers = {name: {**definition, "_plugin": None, "_plugin_enabled": True}
               for name, definition in configured.items() if isinstance(definition, dict)} if isinstance(configured, dict) else {}
    for plugin in discover():
        for name, definition in plugin.mcp_servers.items():
            definition = expand_definition(definition, plugin.path)
            servers.setdefault(f"{plugin.name}__{name}" if plugin.imported else name,
                {**definition, "read_paths": [str(plugin.path), *definition.get("read_paths", [])],
                 "_plugin": plugin.name, "_plugin_enabled": config.plugin_enabled(plugin.name)})
    return servers


def merged_mcp_servers(config) -> dict[str, dict[str, Any]]:
    """Only servers explicitly enabled through /mcp are executable."""
    enabled = config.get("mcp_enabled", {})
    merged = {}
    for name, definition in available_mcp_servers(config).items():
        if enabled.get(name) is not True or not definition["_plugin_enabled"]:
            continue
        owner = definition["_plugin"]
        definition = {key: value for key, value in definition.items()
                      if key not in {"_plugin", "_plugin_enabled"}}
        if owner == "omniroute" and definition.get("eirene_provider") == "omniroute":
            from .omniroute_mcp import bind
            definition = bind(definition, config)
        from .plugin_adapters import bind_mcp
        definition = bind_mcp(definition, owner)
        merged[name] = definition
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


def executable_enabled(plugin: Plugin, config) -> bool:
    return not plugin.imported or bool(config.get("plugin_trust", {}).get(plugin.name, False))


def expand_definition(value, root: Path):
    if isinstance(value, str):
        for key in ("${CLAUDE_PLUGIN_ROOT}", "${CODEX_PLUGIN_ROOT}", "${PLUGIN_ROOT}"):
            value = value.replace(key, str(root))
        return value
    if isinstance(value, list):
        return [expand_definition(item, root) for item in value]
    if isinstance(value, dict):
        return {key: expand_definition(item, root) for key, item in value.items()}
    return value
