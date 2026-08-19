"""Permission bridge between Claude Code's subprocess and Eirene's UI."""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

from ..tools import files
from ..tools.registry import CHAT_OPTION
from ..tools.sandbox import Sandbox

ApprovalFn = Callable[[str, str, str, str], Awaitable[str]]
ChoiceFn = Callable[[str, list], Awaitable[Any]]


SERVER = "eirene"
ASK_TOOL = f"mcp__{SERVER}__ask_user"
APPROVE_TOOL = f"mcp__{SERVER}__approve"


class PermissionBroker:
    """Expose an authenticated loopback approval endpoint to an MCP child."""

    def __init__(self, root: Path, approve: ApprovalFn | None = None,
                 choose: ChoiceFn | None = None, fallback: str = "allow") -> None:
        self.root = root
        self.approve = approve
        self.choose = choose
        self.fallback = fallback
        self.token = secrets.token_urlsafe(24)
        self.server: asyncio.Server | None = None
        self.port = 0
        self.always: set[str] = set()

    async def start(self) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = int(self.server.sockets[0].getsockname()[1])

    async def close(self) -> None:
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
            self.server = None

    def command(self) -> tuple[str, list[str], dict[str, str]]:
        args = ["--permission-proxy", f"{self.port}:{self.token}"]
        if getattr(sys, "frozen", False):
            return sys.executable, args, {}
        package = str(Path(__file__).resolve().parents[2])
        existing = os.environ.get("PYTHONPATH", "")
        joined = os.pathsep.join(part for part in (package, existing) if part)
        return sys.executable, ["-m", "eirene", *args], {"PYTHONPATH": joined}

    async def _handle(self, reader: asyncio.StreamReader,
                      writer: asyncio.StreamWriter) -> None:
        try:
            raw = await asyncio.wait_for(reader.readline(), 3600)
            request = json.loads(raw)
            if not secrets.compare_digest(str(request.get("token") or ""), self.token):
                response = _deny("invalid permission bridge token")
            elif str(request.get("kind") or "") == "ask":
                response = await self._answer(str(request.get("question") or ""),
                                              request.get("options") or [])
            else:
                response = await self._decide(str(request.get("tool_name") or ""),
                                              request.get("input") or {})
            writer.write((json.dumps(response) + "\n").encode())
            await writer.drain()
        except Exception as exc:  # noqa: BLE001
            writer.write((json.dumps(_deny(f"permission check failed: {exc}")) +
                          "\n").encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    async def _answer(self, question: str, options: list) -> dict[str, Any]:
        """Put a Claude Code question to the Eirene user."""
        picked = [str(option).strip() for option in options if str(option).strip()][:6]
        if self.choose is None or not picked:
            return {"answer": "no one is here to answer; decide yourself and "
                              "say what you assumed"}
        try:
            chosen = await self.choose(question or "which one?", picked)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            return {"answer": f"the question could not be shown ({exc}); decide yourself"}
        if chosen is None or chosen == CHAT_OPTION:
            return {"answer": "the user wants to talk it through instead of picking; "
                              "stop and ask them in plain text"}
        return {"answer": str(chosen)}

    async def _decide(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool_name == ASK_TOOL or tool_name in self.always:
            return _allow(arguments)
        if self.approve is None:
            return (_deny("plan mode makes no changes")
                    if self.fallback == "deny" else _allow(arguments))
        name, label, preview = describe_change(tool_name, arguments, self.root)
        reason = "Claude Code wants to modify files" if preview else "Claude Code tool"
        answer = await self.approve(name, label, preview, reason)
        if answer == "always":
            self.always.add(tool_name)
        return _allow(arguments) if answer in ("yes", "always") else _deny(
            "Denied by the user")


def describe_change(tool_name: str, arguments: dict[str, Any],
                    root: Path) -> tuple[str, str, str]:
    """Build an Eirene label and diff from Claude Code tool input."""
    box = Sandbox(root)
    path = str(arguments.get("file_path") or arguments.get("path") or "workspace files")
    if tool_name in ("Write", "write_file"):
        content = str(arguments.get("content") or "")
        return "native_write_file", path, files.diff_preview(box, path, content)
    if tool_name in ("Edit", "edit_file"):
        old = str(arguments.get("old_string") or arguments.get("old") or "")
        new = str(arguments.get("new_string") or arguments.get("new") or "")
        preview = files.edit_preview(box, path, old, new,
                                     bool(arguments.get("replace_all", False)))
        return "native_edit_file", path, preview
    if tool_name in ("MultiEdit",):
        previews = []
        for edit in arguments.get("edits") or []:
            if isinstance(edit, dict):
                previews.append(files.edit_preview(
                    box, path, str(edit.get("old_string") or ""),
                    str(edit.get("new_string") or ""),
                    bool(edit.get("replace_all", False))))
        return "native_edit_file", path, "\n".join(previews)
    command = str(arguments.get("command") or arguments.get("cmd") or tool_name)
    return "run_command", command, ""


def _allow(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"behavior": "allow", "updatedInput": arguments}


def _deny(message: str) -> dict[str, Any]:
    return {"behavior": "deny", "message": message}


TOOL_SCHEMAS = [
    {"name": "approve",
     "description": "Ask the Eirene user to approve a Claude Code tool",
     "inputSchema": {"type": "object", "properties": {
         "tool_name": {"type": "string"}, "input": {"type": "object"}},
         "required": ["tool_name", "input"]}},
    {"name": "ask_user",
     "description": "Ask the Eirene user to choose between options. Use this "
                    "instead of ending your turn with a question, so they can "
                    "answer with one key.",
     "inputSchema": {"type": "object", "properties": {
         "question": {"type": "string",
                      "description": "What you need decided, in one line."},
         "options": {"type": "array", "items": {"type": "string"},
                     "description": "Two to five short answers to choose from."}},
         "required": ["question", "options"]}},
]


def proxy_main(port: int, token: str) -> int:
    """Serve the tiny stdio MCP endpoint Claude Code invokes for permission."""
    for line in sys.stdin:
        try:
            request = json.loads(line)
            ident = request.get("id")
            method = request.get("method")
            if ident is None:
                continue
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "eirene-permissions", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": TOOL_SCHEMAS}
            elif method == "tools/call":
                params = request.get("params") or {}
                args = params.get("arguments") or {}
                if str(params.get("name") or "") == "ask_user":
                    reply = _relay(port, token, {
                        "kind": "ask", "question": args.get("question"),
                        "options": args.get("options") or []})
                    text = str(reply.get("answer") or "")
                else:
                    text = json.dumps(_relay(port, token, {
                        "kind": "approve", "tool_name": args.get("tool_name"),
                        "input": args.get("input") or {}}))
                result = {"content": [{"type": "text", "text": text}]}
            else:
                _write({"jsonrpc": "2.0", "id": ident, "error": {
                    "code": -32601, "message": "method not found"}})
                continue
            _write({"jsonrpc": "2.0", "id": ident, "result": result})
        except Exception as exc:  # noqa: BLE001
            _write({"jsonrpc": "2.0", "id": request.get("id"), "error": {
                "code": -32603, "message": str(exc)}})
    return 0


def _relay(port: int, token: str, payload: dict[str, Any]) -> dict[str, Any]:
    payload = {"token": token, **payload}
    with socket.create_connection(("127.0.0.1", port), timeout=3610) as connection:
        connection.sendall((json.dumps(payload) + "\n").encode())
        stream = connection.makefile("rb")
        return json.loads(stream.readline())


def _write(message: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()
