"""Translate Eirene stdio definitions into native CLI configuration."""
from __future__ import annotations


def native_servers(definitions: dict) -> dict:
    servers = {}
    for name, definition in definitions.items():
        from ..core.mcp_config import transport
        if transport(definition) != 'stdio' or definition.get('auto_setup'):
            from ..core.mcp_proxy import proxy_definition
            servers[name] = proxy_definition(name)
            continue
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
