"""Notifications when the set of live commands changes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Awaitable
import uuid

from ..core.errors import ToolError

_listeners: set[Callable[[], None]] = set()


@dataclass
class ProviderCommand:
    id: str
    label: str
    stop: Callable[[], Awaitable[None]]


_provider_commands: dict[str, ProviderCommand] = {}


def subscribe(listener: Callable[[], None]) -> None:
    _listeners.add(listener)


def unsubscribe(listener: Callable[[], None]) -> None:
    _listeners.discard(listener)


def changed() -> None:
    for listener in tuple(_listeners):
        try:
            listener()
        except Exception:  # noqa: BLE001
            pass


def start_provider_command(label: str,
                           stop: Callable[[], Awaitable[None]]) -> str:
    """Expose a command owned by an external subscription CLI."""
    command_id = uuid.uuid4().hex[:10]
    _provider_commands[command_id] = ProviderCommand(command_id, label, stop)
    changed()
    return command_id


def finish_provider_command(command_id: str) -> None:
    if _provider_commands.pop(command_id, None) is not None:
        changed()


def provider_commands() -> list[tuple[str, str]]:
    return [(f"{item.id}  {item.label}", item.id)
            for item in _provider_commands.values()]


async def stop_provider_command(command_id: str) -> str:
    item = _provider_commands.get(command_id.strip())
    if item is None:
        raise ToolError(f"no running provider command '{command_id}'")
    await item.stop()
    finish_provider_command(item.id)
    return f"stopped {item.id}"
