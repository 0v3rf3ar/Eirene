"""HTTP and legacy SSE MCP sessions, owned and closed by one asyncio task."""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from datetime import timedelta

import httpx

from .errors import ToolError
from .mcp import MCPClient, MCPTool, REQUEST_TIMEOUT, _safe, _timeout
from .mcp_auth import MCPSecrets, OAuthLogin
from .mcp_config import normalize, transport


def _failure(name: str, error: BaseException) -> ToolError:
    if isinstance(error, BaseExceptionGroup):
        return _failure(name, error.exceptions[0])
    if isinstance(error, ToolError):
        return error
    if type(error).__name__ == 'OAuthRegistrationError':
        return ToolError(f'MCP {name}: this server requires a registered OAuth application; '
                         f'use /mcp login {name} → Registered OAuth application, or include oauth client settings in the JSON')
    if isinstance(error, httpx.HTTPStatusError):
        if error.response.status_code in (401, 403):
            return ToolError(f'MCP {name}: authentication or permissions required; run /mcp login {name}')
        return ToolError(f'MCP {name}: HTTP {error.response.status_code}; check the MCP URL')
    # HTTP exceptions and server text can contain headers, tokens, or URL secrets.
    return ToolError(f'MCP {name}: connection failed ({type(error).__name__}); check the URL, network, and authentication')


class RemoteMCPClient(MCPClient):
    def __init__(self, name, definition, sandbox, *, interactive=False, say=None):
        super().__init__(name, normalize(definition), sandbox)
        self.interactive, self.say = interactive, say
        self.worker = None
        self.pending = asyncio.Queue()
        self.ready = None

    async def connect(self) -> list[MCPTool]:
        if self.definition.get('_isolate_network') is True:
            raise ToolError(f'MCP {self.name}: network access is disabled in this declaration')
        self.ready = asyncio.get_running_loop().create_future()
        self.worker = asyncio.create_task(self._serve())
        timeout = 360 if self.interactive else _timeout(self.definition.get('startup_timeout'), REQUEST_TIMEOUT)
        try:
            return await asyncio.wait_for(asyncio.shield(self.ready), timeout)
        except asyncio.TimeoutError as exc:
            await self.close()
            raise ToolError(f'MCP {self.name}: connection timed out') from exc
        except BaseException:
            await self.close()
            raise

    async def _serve(self):
        current = None
        try:
            from mcp import ClientSession
            from mcp.client.sse import sse_client
            from mcp.client.streamable_http import streamable_http_client
            async with AsyncExitStack() as stack:
                secret = MCPSecrets(self.name, self.definition['url']).read()
                headers = {key.lower(): value for key, value in self.definition.get('headers', {}).items()}
                headers.update({key.lower(): value for key, value in secret.get('headers', {}).items()})
                auth = None
                mode = secret.get('auth', self.definition.get('auth', 'auto'))
                if mode == 'oauth' or (mode == 'auto' and (self.interactive or secret.get('tokens'))):
                    auth = await stack.enter_async_context(OAuthLogin(
                        self.name, {**self.definition, 'oauth': {**self.definition.get('oauth', {}), **secret.get('oauth', {})}},
                        interactive=self.interactive, say=self.say))
                timeout = _timeout(self.definition.get('request_timeout'), REQUEST_TIMEOUT)
                if transport(self.definition) == 'sse':
                    streams = await stack.enter_async_context(sse_client(
                        self.definition['url'], headers=headers, auth=auth, timeout=timeout))
                else:
                    http = await stack.enter_async_context(httpx.AsyncClient(
                        headers=headers, auth=auth, timeout=httpx.Timeout(timeout, read=360), follow_redirects=False))
                    streams = await stack.enter_async_context(streamable_http_client(
                        self.definition['url'], http_client=http))
                session = await stack.enter_async_context(ClientSession(
                    streams[0], streams[1], read_timeout_seconds=timedelta(seconds=360 if self.interactive else timeout)))
                initialized = await session.initialize()
                self.instructions = initialized.instructions or ''
                tools, seen, cursor = [], set(), None
                while True:
                    page = await session.list_tools(cursor=cursor)
                    tools.extend(MCPTool(self.name, tool.name, f'mcp__{_safe(self.name)}__{_safe(tool.name)}',
                                         tool.description or tool.name, tool.inputSchema) for tool in page.tools)
                    cursor = page.nextCursor
                    if not cursor:
                        break
                    if cursor in seen or len(seen) >= 100 or len(tools) > 2000:
                        raise ToolError(f'MCP {self.name}: invalid or excessive tool pagination')
                    seen.add(cursor)
                self.ready.set_result(tools)
                while True:
                    current = await self.pending.get()
                    if current is None:
                        break
                    params, future = current
                    if not future.cancelled():
                        try:
                            result = await session.call_tool(params['name'], params.get('arguments', {}),
                                                            read_timeout_seconds=timedelta(seconds=timeout))
                            if not future.done():
                                future.set_result(result.model_dump(mode='json', by_alias=True))
                        except Exception as exc:
                            if not future.done():
                                future.set_exception(_failure(self.name, exc))
                    current = None
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failure = _failure(self.name, exc)
            if not self.ready.done():
                self.ready.set_exception(failure)
        finally:
            failure = ToolError(f'MCP {self.name}: connection closed; retry the connection')
            if current and not current[1].done():
                current[1].set_exception(failure)
            while not self.pending.empty():
                item = self.pending.get_nowait()
                if item and not item[1].done():
                    item[1].set_exception(failure)

    async def request(self, method, params, *, timeout=None):
        if method != 'tools/call' or not self.worker or self.worker.done():
            raise ToolError(f'MCP {self.name}: connection is not ready')
        future = asyncio.get_running_loop().create_future()
        await self.pending.put((params, future))
        try:
            return await asyncio.wait_for(future, _timeout(timeout or self.definition.get('request_timeout'), REQUEST_TIMEOUT))
        except asyncio.TimeoutError as exc:
            await self.close()
            raise ToolError(f'MCP {self.name}: tool request timed out') from exc

    async def close(self):
        if self.worker:
            worker, self.worker = self.worker, None
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


def make_client(name, definition, sandbox, *, interactive=False, say=None):
    if transport(definition) != 'stdio':
        return RemoteMCPClient(name, definition, sandbox, interactive=interactive, say=say)
    from .mcp_config import prepare_local
    definition = prepare_local(name, definition) if definition.get('auto_setup') else normalize(definition)
    return MCPClient(name, definition, sandbox)
