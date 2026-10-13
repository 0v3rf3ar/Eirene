"""Expose conversation attachments to native CLI providers over stdio MCP."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from ..core import paths
from ..core.attachments import attachment_image, read_attachment
from ..core.errors import EireneError, ToolError
from ..core.session import read_records
from ..tools.registry import BY_NAME


def definition(session_id: str) -> dict:
    argv = ["--attachment-reader", session_id]
    env = {paths.ENV_HOME: str(paths.home().resolve())}
    if not getattr(sys, "frozen", False):
        argv = ["-m", "eirene", *argv]
        env["PYTHONPATH"] = os.pathsep.join(filter(None, (
            str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", ""))))
    return {"command": sys.executable, "args": argv, "env": env}


def call(session_id: str, args: dict) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", session_id):
        raise ToolError("invalid session ID")
    available = {item["id"]: item
                 for record in read_records(paths.sessions_dir() / f"{session_id}.jsonl")
                 if record.get("t") == "user" for item in record.get("files") or []}
    item = available.get(str(args.get("attachment_id", "")))
    if item is None:
        raise ToolError("attachment is not available in this conversation")
    text = read_attachment(item, int(args.get("offset", 0)), int(args.get("limit", 4096)),
                           encoding=str(args.get("encoding", "auto")))
    content = [{"type": "text", "text": text}]
    if args.get("encoding", "auto") == "auto":
        image = attachment_image(item)
        if image:
            content.append({"type": "image", "data": image["data"], "mimeType": image["mime_type"]})
    return {"content": content}


def reader_main(session_id: str) -> int:
    tool = BY_NAME["read_attachment"]
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                request = {}
                raise ValueError("request must be an object")
            ident = request.get("id")
            if ident is None:
                continue
            method = request.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "eirene-attachments", "version": "1"}}
            elif method == "tools/list":
                result = {"tools": [{"name": tool.name, "description": tool.description,
                                     "inputSchema": tool.schema}]}
            elif method == "tools/call":
                params = request.get("params") or {}
                try:
                    if params.get("name") != tool.name:
                        raise ToolError("unknown attachment tool")
                    result = call(session_id, params.get("arguments") or {})
                except (EireneError, OSError, ValueError) as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            elif method == "ping":
                result = {}
            else:
                raise ValueError("method not found")
            response = {"jsonrpc": "2.0", "id": ident, "result": result}
        except (ValueError, TypeError, AttributeError) as exc:
            response = {"jsonrpc": "2.0", "id": request.get("id"),
                        "error": {"code": -32603, "message": str(exc)}}
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()
    return 0
