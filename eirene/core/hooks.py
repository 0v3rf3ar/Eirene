"""Configured before/after tool command hooks."""

from __future__ import annotations

from ..tools import shell
from .errors import ToolError
from .plugins import merged_hooks
from .permissions import isolation, isolate_network


async def run(event: str, tool_name: str, sandbox, config, *, failed: bool = False) -> list[str]:
    commands = merged_hooks(config).get(event, [])
    notes = []
    for command in commands:
        result = await shell.run(
            command, sandbox.root,
            timeout=float(config.get("shell_timeout", 120) or 120),
            max_bytes=min(int(config.get("max_output_bytes", 200_000)), 50_000),
            env={"EIRENE_HOOK_EVENT": event, "EIRENE_TOOL_NAME": tool_name,
                 "EIRENE_TOOL_FAILED": "1" if failed else "0"},
            isolation=isolation(config),
            isolate_network=isolate_network(config))
        if not result.ok:
            raise ToolError(f"{event} hook failed: {result.summary()}")
        notes.append(command)
    return notes
