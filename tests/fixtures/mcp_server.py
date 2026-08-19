"""Tiny JSON-lines MCP server used by the test suite."""

from __future__ import annotations

import json
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fixture", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo-value", "description": "Echo a value",
                             "inputSchema": {"type": "object", "properties": {
                                 "value": {"type": "string"}}, "required": ["value"]}}]}
    elif method == "tools/call":
        value = request.get("params", {}).get("arguments", {}).get("value", "")
        result = {"content": [{"type": "text", "text": f"echo:{value}"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                          "error": {"code": -32601, "message": "unknown"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}),
          flush=True)
