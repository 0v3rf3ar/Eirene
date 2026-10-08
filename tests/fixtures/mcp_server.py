"""Tiny JSON-lines MCP server used by the test suite."""

from __future__ import annotations

import json
import os
import sys

for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "fixture", "version": "1"}}
        if os.environ.get("EIRENE_TEST_PAGED_MCP"):
            result["instructions"] = "Activate the current project before symbol edits."
            print(json.dumps({"jsonrpc": "2.0", "id": "server-ping", "method": "ping"}), flush=True)
            response = json.loads(next(sys.stdin))
            assert response == {"jsonrpc": "2.0", "id": "server-ping", "result": {}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo-value", "description": "Echo a value",
                             "inputSchema": {"type": "object", "properties": {
                                 "value": {"type": "string"}}, "required": ["value"]}}]}
        if os.environ.get("EIRENE_TEST_LARGE_MCP"):
            result["tools"] = [{**result["tools"][0], "name": f"tool-{index}",
                                "description": "Gateway tool " * 100}
                               for index in range(110)]
        if os.environ.get("EIRENE_TEST_PAGED_MCP"):
            cursor = request.get("params", {}).get("cursor")
            if cursor:
                result["tools"][0]["name"] = "last-page"
            else:
                result["nextCursor"] = "page-two"
    elif method == "tools/call":
        value = request.get("params", {}).get("arguments", {}).get("value", "")
        result = {"content": [{"type": "text", "text": f"echo:{value}"}]}
    else:
        print(json.dumps({"jsonrpc": "2.0", "id": request["id"],
                          "error": {"code": -32601, "message": "unknown"}}), flush=True)
        continue
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}),
          flush=True)
