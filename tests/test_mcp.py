"""MCP stdio discovery, calls, errors, and cleanup."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from eirene.core.errors import ToolError
from eirene.core.mcp import MCPManager

SERVER = Path(__file__).parent / "fixtures" / "mcp_server.py"


async def test_paginated_tools_server_ping_and_instructions(workdir):
    manager = MCPManager({"serena": {"command": [sys.executable, str(SERVER)],
        "env": {"EIRENE_TEST_PAGED_MCP": "1"}}}, workdir)
    try:
        await manager.ensure()
        assert not manager.errors
        assert len(manager.specs()) == 2
        assert "Activate the current project" in manager.instruction_block()
        assert await manager.call("mcp__serena__last-page", {"value": "page2"}) == "echo:page2"
    finally:
        await manager.close()


async def test_large_gateway_catalogue_is_not_truncated(workdir):
    manager = MCPManager({"gateway": {"command": [sys.executable, str(SERVER)],
                          "env": {"EIRENE_TEST_LARGE_MCP": "1"}}}, workdir)
    await manager.ensure()
    try:
        assert manager.errors == []
        assert len(manager.specs()) == 110
        assert await manager.call("mcp__gateway__tool-109", {"value": "last"}) == "echo:last"
    finally:
        await manager.close()


async def test_mcp_discovers_namespaced_tools_and_calls_them(workdir):
    manager = MCPManager({"demo server": {"command": [sys.executable, str(SERVER)]}},
                         workdir)
    await manager.ensure()
    try:
        assert manager.errors == []
        assert manager.owns("mcp__demo_server__echo-value")
        spec = manager.specs()[0]
        assert spec["parameters"]["required"] == ["value"]
        result = await manager.call("mcp__demo_server__echo-value", {"value": "hello"})
        assert result == "echo:hello"
    finally:
        clients = list(manager.clients.values())
        await manager.close()
    assert all(client.process is None for client in clients)


async def test_bad_server_is_reported_without_breaking_other_servers(workdir):
    manager = MCPManager({
        "bad": {"command": ["definitely-missing-mcp-command"]},
        "good": {"command": [sys.executable, str(SERVER)]},
    }, workdir)
    await manager.ensure()
    try:
        assert len(manager.errors) == 1
        assert manager.owns("mcp__good__echo-value")
    finally:
        await manager.close()


async def test_unknown_mcp_tool_is_rejected(workdir):
    manager = MCPManager({}, workdir)
    with pytest.raises(ToolError, match="unknown MCP tool"):
        await manager.call("mcp__none__missing", {})


async def test_mcp_cwd_cannot_escape_sandbox(workdir):
    manager = MCPManager({"bad": {"command": [sys.executable, str(SERVER)],
                                  "cwd": "../outside"}}, workdir)
    await manager.ensure()
    assert manager.errors and "leaves the sandbox" in manager.errors[0]
