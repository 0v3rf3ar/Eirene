"""Minimal MCP stdio client and namespaced tool registry."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ToolError

PROTOCOL_VERSION = "2025-03-26"
REQUEST_TIMEOUT = 30.0


@dataclass
class MCPTool:
    server: str
    remote_name: str
    name: str
    description: str
    schema: dict[str, Any]


class MCPClient:
    def __init__(self, name: str, definition: dict[str, Any], sandbox: Path):
        self.name = name
        self.definition = definition
        self.sandbox = sandbox
        self.process: asyncio.subprocess.Process | None = None
        self.next_id = 1
        self.lock = asyncio.Lock()
        self.stderr_tail = bytearray()
        self.stderr_task = None

    async def connect(self) -> list[MCPTool]:
        command = self.definition.get("command")
        if isinstance(command, str):
            command = [command]
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ToolError(f"MCP server {self.name} has no valid command")
        cwd = self.sandbox
        raw_cwd = self.definition.get("cwd")
        if raw_cwd:
            candidate = (self.sandbox / str(raw_cwd)).resolve()
            if candidate != self.sandbox and self.sandbox not in candidate.parents:
                raise ToolError(f"MCP server {self.name} cwd leaves the sandbox")
            cwd = candidate
        env = dict(os.environ)
        configured_env = self.definition.get("env")
        if isinstance(configured_env, dict):
            env.update({str(k): str(v) for k, v in configured_env.items()})
        backend = self.definition.get("_isolation", "none")
        if backend != "none":
            from ..tools import isolation
            command = isolation.command(shlex.join(command), cwd, backend=backend,
                network=not self.definition.get("_isolate_network", True),
                read_paths=self.definition.get("read_paths", []),
                write_paths=self.definition.get("write_paths", []))
            env = isolation.environment(configured_env if isinstance(configured_env, dict) else {})
        try:
            self.process = await asyncio.create_subprocess_exec(
                *command, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                start_new_session=os.name != "nt")
            self.stderr_task = asyncio.create_task(self._drain_stderr())
            await self.request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "eirene", "version": "0.1.0"},
            })
            await self.notify("notifications/initialized", {})
            result = await self.request("tools/list", {})
        except OSError as exc:
            await self.close()
            raise ToolError(f"cannot start MCP server {self.name}: {exc}") from exc
        except Exception:
            await self.close()
            raise
        tools = []
        for raw in result.get("tools", []) if isinstance(result, dict) else []:
            if not isinstance(raw, dict) or not raw.get("name"):
                continue
            remote = str(raw["name"])
            public = f"mcp__{_safe(self.name)}__{_safe(remote)}"
            schema = raw.get("inputSchema")
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}
            tools.append(MCPTool(self.name, remote, public,
                                 str(raw.get("description") or remote), schema))
        return tools

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        result = await self.request("tools/call", {"name": name,
                                                   "arguments": arguments})
        if not isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        blocks = []
        for item in result.get("content", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                blocks.append(str(item.get("text") or ""))
            else:
                blocks.append(json.dumps(item, ensure_ascii=False))
        text = "\n".join(blocks).strip() or "(no content)"
        if result.get("isError"):
            raise ToolError(text)
        return text

    async def request(self, method: str, params: dict[str, Any]) -> Any:
        async with self.lock:
            request_id = self.next_id
            self.next_id += 1
            await self._write({"jsonrpc": "2.0", "id": request_id,
                               "method": method, "params": params})
            while True:
                message = await self._read()
                if message.get("id") != request_id:
                    continue
                if "error" in message:
                    error = message.get("error") or {}
                    raise ToolError(f"MCP {self.name}: {error.get('message') or error}")
                return message.get("result")

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params})

    async def _write(self, message: dict) -> None:
        if not self.process or not self.process.stdin:
            raise ToolError(f"MCP server {self.name} is not running")
        self.process.stdin.write((json.dumps(message, separators=(",", ":")) + "\n").encode())
        await self.process.stdin.drain()

    async def _read(self) -> dict:
        if not self.process or not self.process.stdout:
            raise ToolError(f"MCP server {self.name} is not running")
        try:
            raw = await asyncio.wait_for(self.process.stdout.readline(), REQUEST_TIMEOUT)
        except asyncio.TimeoutError as exc:
            raise ToolError(f"MCP server {self.name} timed out") from exc
        if not raw:
            detail = self.stderr_tail.decode("utf-8", "replace").strip()
            raise ToolError(f"MCP server {self.name} exited" + (f": {detail}" if detail else ""))
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ToolError(f"MCP server {self.name} sent invalid JSON") from exc
        if not isinstance(value, dict):
            raise ToolError(f"MCP server {self.name} sent a non-object response")
        return value

    async def close(self) -> None:
        process = self.process
        self.process = None
        if process:
            from ..tools.shell import _kill_tree
            await _kill_tree(process)
        if self.stderr_task:
            self.stderr_task.cancel()
            await asyncio.gather(self.stderr_task, return_exceptions=True)
            self.stderr_task = None

    async def _drain_stderr(self):
        stream = self.process.stderr if self.process else None
        if stream:
            while chunk := await stream.read(8192):
                self.stderr_tail.extend(chunk)
                del self.stderr_tail[:-8192]


class MCPManager:
    def __init__(self, definitions: dict[str, dict[str, Any]], sandbox: Path):
        self.definitions = definitions
        self.sandbox = sandbox
        self.clients: dict[str, MCPClient] = {}
        self.tools: dict[str, MCPTool] = {}
        self.errors: list[str] = []
        self.ready = False

    async def ensure(self) -> None:
        if self.ready:
            return
        self.ready = True
        for name, definition in self.definitions.items():
            client = MCPClient(str(name), definition, self.sandbox)
            try:
                tools = await client.connect()
            except ToolError as exc:
                self.errors.append(str(exc))
                continue
            self.clients[str(name)] = client
            for tool in tools:
                self.tools[tool.name] = tool

    def specs(self) -> list[dict[str, Any]]:
        return [{"name": tool.name, "description": tool.description,
                 "parameters": tool.schema} for tool in self.tools.values()]

    def owns(self, name: str) -> bool:
        return name in self.tools

    async def call(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.tools.get(name)
        if tool is None:
            raise ToolError(f"unknown MCP tool '{name}'")
        return await self.clients[tool.server].call(tool.remote_name, arguments)

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self.clients.values()),
                             return_exceptions=True)
        self.clients.clear()
        self.tools.clear()
        self.ready = False


def _safe(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_") or "tool"
