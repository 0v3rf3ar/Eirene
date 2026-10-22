"""Opt-in checks of actual browser packages; downloads require network access."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from eirene.core.mcp_config import import_json, prepare_local
from eirene.core.mcp_import import resolve_definition
from eirene.core.mcp_remote import make_client
from eirene.core.mcp import MCPClient
from eirene.core.mcp_proxy import proxy_definition

pytestmark = pytest.mark.skipif(os.environ.get('EIRENE_LIVE_MCP') != '1', reason='opt-in npm/browser integration')


@pytest.mark.parametrize('name,tool,args', [
    ('playwright', 'browser_navigate', {'url': 'about:blank'}),
    ('chrome-devtools', 'list_pages', {}),
    ('puppeteer', 'puppeteer_navigate', {'url': 'about:blank'}),
])
async def test_published_browser_json_runs_real_tool(name, tool, args, workdir, monkeypatch, config):
    monkeypatch.delenv('DISPLAY', raising=False)
    monkeypatch.delenv('WAYLAND_DISPLAY', raising=False)
    path = Path(__file__).parents[1] / 'docs/mcp-examples' / (name + '.json')
    raw = next(iter(import_json(path.read_text()).values()))
    definition = await resolve_definition(raw, workdir, AsyncMock(), AsyncMock())
    definition = prepare_local(name, definition)
    definition['startup_timeout'] = 180
    definition['request_timeout'] = 60
    if binary := os.environ.get('EIRENE_TEST_MCP_BINARY'):
        definition['auto_setup'] = True
        config.set('mcp_servers', {name: definition})
        config.set('mcp_enabled', {name: True})
        config.save()
        proxy = proxy_definition(name)
        client = MCPClient('frozen', {'command': [binary, '--mcp-proxy', name], 'env': proxy['env'],
                                     'startup_timeout': 180, 'request_timeout': 60}, workdir)
    else:
        client = make_client(name, definition, workdir)
    try:
        tools = await client.connect()
        assert any(item.remote_name == tool for item in tools)
        result = await client.call(tool, args)
        assert result
    finally:
        await client.close()
