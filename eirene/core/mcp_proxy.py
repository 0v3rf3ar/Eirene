"""Expose saved remote connections to native providers without exporting tokens."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from . import paths
from .config import Config
from .errors import ToolError
from .mcp_remote import make_client
from .plugins import merged_mcp_servers


def proxy_definition(name: str) -> dict:
    argv = ['--mcp-proxy', name]
    env = {paths.ENV_HOME: str(paths.home().resolve())}
    if not getattr(sys, 'frozen', False):
        argv = ['-m', 'eirene', *argv]
        env['PYTHONPATH'] = os.pathsep.join(filter(None, (
            str(Path(__file__).resolve().parents[2]), os.environ.get('PYTHONPATH', ''))))
    return {'command': sys.executable, 'args': argv, 'env': env}


async def _run(name: str) -> int:
    definition = merged_mcp_servers(Config.load()).get(name)
    if definition is None:
        sys.stderr.write('MCP connection is disabled or unavailable\n')
        return 1
    client = make_client(name, definition, Path.cwd())
    try:
        tools = await client.connect()
        while line := await asyncio.to_thread(sys.stdin.readline):
            request = {}
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError('request must be an object')
                if 'id' not in request:
                    continue
                method, params = request.get('method'), request.get('params', {})
                if method == 'initialize':
                    result = {'protocolVersion': params.get('protocolVersion', '2025-03-26'),
                              'capabilities': {'tools': {}},
                              'serverInfo': {'name': 'eirene-' + name, 'version': '1'},
                              'instructions': client.instructions}
                elif method == 'tools/list':
                    result = {'tools': [{'name': tool.remote_name, 'description': tool.description,
                                         'inputSchema': tool.schema} for tool in tools]}
                elif method == 'tools/call':
                    if params.get('name') not in {tool.remote_name for tool in tools}:
                        raise ToolError('unknown MCP tool')
                    result = await client.request(method, params)
                elif method == 'ping':
                    result = {}
                else:
                    raise ToolError('client method not supported')
                response = {'jsonrpc': '2.0', 'id': request['id'], 'result': result}
            except (ValueError, ToolError) as exc:
                response = {'jsonrpc': '2.0', 'id': request.get('id') if isinstance(request, dict) else None,
                            'error': {'code': -32603, 'message': str(exc)}}
            sys.stdout.write(json.dumps(response) + '\n')
            sys.stdout.flush()
    except (ToolError, ValueError) as exc:
        sys.stderr.write(str(exc) + '\n')
        return 1
    finally:
        await client.close()
    return 0


def proxy_main(name: str) -> int:
    return asyncio.run(_run(name))
