"""Translate Eirene stdio definitions into native CLI configuration."""
from __future__ import annotations


def native_servers(definitions: dict) -> dict:
    servers = {}
    for name, definition in definitions.items():
        command = definition.get("command")
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command:
            continue
        servers[name] = {"command": command[0],
                         "args": command[1:] + definition.get("args", [])}
        for key in ("env", "cwd"):
            if key in definition:
                servers[name][key] = definition[key]
    return servers
