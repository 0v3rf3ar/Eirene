"""Normalize portable Claude/Codex plugin bundles without executing them."""
from __future__ import annotations

import json
import re
from pathlib import Path

SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit"}


def inside(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if path != root.resolve() and root.resolve() not in path.parents:
        raise ValueError(f"plugin path leaves its directory: {value}")
    return path


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected a JSON object in {path.name}")
    return value


def normalize(root: Path, fallback: str) -> dict:
    manifest = next((p for p in (root / ".claude-plugin/plugin.json",
                                root / ".codex-plugin/plugin.json",
                                root / ".agent-plugin/plugin.json",
                                root / ".github/plugin/plugin.json",
                                root / "plugin.json") if p.is_file()), None)
    body = read_object(manifest) if manifest else {}
    name = body.get("name", fallback)
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
        raise ValueError("plugin must have a simple alphanumeric name")
    warnings = []

    def markdown(key: str, defaults: list[str]) -> list[str]:
        raw = body.get(key, [])
        if isinstance(raw, str):
            raw = [raw]
        if not isinstance(raw, list):
            warnings.append(f"unsupported {key} declaration")
            raw = []
        found = set()
        for value in defaults + raw:
            if not isinstance(value, str):
                raise ValueError(f"invalid {key} path")
            path = inside(root, value)
            candidates = path.rglob("*.md") if path.is_dir() else [path]
            for item in candidates:
                inside(root, str(item))
                if item.is_file() and item.suffix == ".md":
                    if key != "skills" or item.name == "SKILL.md" or item.parent == root / "skills" or item == path:
                        found.add(item.relative_to(root).as_posix())
        return sorted(found)

    skills = markdown("skills", ["skills", "SKILL.md"])
    commands = markdown("commands", ["commands"])
    agents = markdown("agents", ["agents"])
    if agents:
        warnings.append("agent definitions are exposed as instruction commands; native subagent spawning is not emulated")
    raw_hooks = body.get("hooks", "hooks/hooks.json")
    if isinstance(raw_hooks, str):
        hook_path = inside(root, raw_hooks)
        raw_hooks = read_object(hook_path) if hook_path.is_file() else {}
    hooks = raw_hooks.get("hooks", raw_hooks) if isinstance(raw_hooks, dict) else {}
    lifecycle = {}
    for event, groups in hooks.items():
        if event not in SUPPORTED_EVENTS:
            warnings.append(f"hook event {event} is not supported by the portable runtime")
            continue
        if not isinstance(groups, list):
            raise ValueError(f"invalid {event} hooks")
        accepted = []
        for group in groups:
            if not isinstance(group, dict):
                raise ValueError(f"invalid {event} hook group")
            matcher = str(group.get("matcher", ""))
            try:
                re.compile(matcher)
            except re.error as exc:
                raise ValueError(f"invalid {event} matcher") from exc
            for hook in group.get("hooks", []):
                if not isinstance(hook, dict) or hook.get("type") != "command" or hook.get("async"):
                    warnings.append(f"only synchronous command hooks are supported ({event})")
                    continue
                command = hook.get("command")
                if not isinstance(command, str) or not command.strip():
                    raise ValueError(f"invalid {event} command")
                accepted.append({"command": command, "matcher": matcher,
                                 "timeout": max(1, min(float(hook.get("timeout", 30)), 120))})
        lifecycle[event] = accepted
    default_mcp = ".mcp.json" if (root / ".mcp.json").is_file() else "mcp.json"
    raw_mcp = body.get("mcpServers", body.get("mcp_servers", default_mcp))
    if isinstance(raw_mcp, str):
        mcp_path = inside(root, raw_mcp)
        raw_mcp = read_object(mcp_path) if mcp_path.is_file() else {}
    servers = raw_mcp.get("mcpServers", raw_mcp) if isinstance(raw_mcp, dict) else {}
    mcp = {}
    for server, definition in servers.items():
        if not isinstance(definition, dict):
            raise ValueError(f"invalid MCP server {server}")
        command = definition.get("command")
        args = definition.get("args", [])
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command or not isinstance(args, list) or not all(isinstance(x, str) for x in command + args):
            warnings.append(f"MCP {server}: only stdio servers with command/args are supported")
            continue
        mcp[str(server)] = {**definition, "command": command + args}
        mcp[str(server)].pop("args", None)
    for feature in ("lspServers", "outputStyles"):
        if body.get(feature):
            warnings.append(f"{feature} requires a native host and is not imported")
    return {"version": 1, "name": name, "description": str(body.get("description", "")),
            "skills": skills, "commands": commands, "agents": agents,
            "lifecycle": lifecycle, "mcp_servers": mcp, "imported": True,
            "warnings": warnings}
