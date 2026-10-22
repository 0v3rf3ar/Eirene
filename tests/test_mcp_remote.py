"""Real HTTP/SSE sessions and private MCP authentication lifecycle."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import socket
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from eirene.core.errors import ToolError
from eirene.core.mcp import MCPManager
from eirene.core.mcp_auth import MCPSecrets, OAuthLogin
from eirene.core.mcp_remote import RemoteMCPClient


@pytest.fixture(params=['http-json', 'http-sse', 'sse'])
async def remote_server(request):
    import uvicorn
    from mcp.server.fastmcp import FastMCP
    from starlette.responses import JSONResponse, Response
    from starlette.requests import Request

    mcp = FastMCP('test-remote', instructions='Use these remote tools.',
                  json_response=request.param == 'http-json')

    @mcp.tool()
    async def echo(value: str) -> str:
        return 'remote:' + value

    @mcp.tool()
    async def fail() -> str:
        raise ValueError('remote tool failed')

    application = mcp.sse_app() if request.param == 'sse' else mcp.streamable_http_app()
    calls = []

    async def authenticated(scope, receive, send):
        if scope['type'] == 'http':
            path = scope['path']
            origin = f'http://127.0.0.1:{port}'
            if path.startswith('/.well-known/oauth-protected-resource'):
                response = JSONResponse({'resource': origin + ('/sse' if request.param == 'sse' else '/mcp'),
                                         'authorization_servers': [origin], 'scopes_supported': ['tools']})
                await response(scope, receive, send)
                return
            if path.startswith('/.well-known/oauth-authorization-server'):
                response = JSONResponse({'issuer': origin, 'authorization_endpoint': origin + '/authorize',
                    'token_endpoint': origin + '/auth/token', 'registration_endpoint': origin + '/register',
                    'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
                    'token_endpoint_auth_methods_supported': ['none'], 'code_challenge_methods_supported': ['S256']})
                await response(scope, receive, send)
                return
            if path == '/register':
                calls.append('registration')
                body = await Request(scope, receive).json()
                await JSONResponse({**body, 'client_id': 'test-client'})(scope, receive, send)
                return
            if path == '/auth/token':
                form = parse_qs((await Request(scope, receive).body()).decode())
                grant = form['grant_type'][0]
                calls.append(grant)
                if grant == 'authorization_code':
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'][0].encode()).digest()).rstrip(b'=').decode()
                    assert challenge == next(item[1] for item in calls if isinstance(item, tuple))
                await JSONResponse({'access_token': 'test-secret', 'token_type': 'Bearer',
                                    'expires_in': 3600, 'refresh_token': 'test-refresh', 'scope': 'tools'})(scope, receive, send)
                return
            headers = dict(scope['headers'])
            if headers.get(b'authorization') != b'Bearer test-secret':
                await Response(status_code=401)(scope, receive, send)
                return
            calls.append(scope['method'])
        await application(scope, receive, send)

    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(authenticated, log_level='critical', lifespan='on', timeout_graceful_shutdown=1)
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(200):
            if server.started:
                break
            if task.done():
                await task
            await asyncio.sleep(.01)
        assert server.started
        kind = 'sse' if request.param == 'sse' else 'http'
        yield {'type': kind, 'url': f'http://127.0.0.1:{port}/' + ('sse' if kind == 'sse' else 'mcp')}, calls
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 5)
        sock.close()


async def test_remote_discovery_calls_errors_and_cleanup(remote_server, workdir):
    definition, calls = remote_server
    MCPSecrets('remote', definition['url']).update(headers={'Authorization': 'Bearer test-secret'})
    manager = MCPManager({'remote': {**definition, 'network': True}}, workdir)
    await manager.ensure()
    try:
        assert manager.errors == []
        assert len(manager.tools) == 2
        assert 'Use these remote tools.' in manager.instruction_block()
        assert await manager.call('mcp__remote__echo', {'value': 'hello'}) == 'remote:hello'
        with pytest.raises(ToolError, match='remote tool failed'):
            await manager.call('mcp__remote__fail', {})
        assert 'POST' in calls
    finally:
        clients = list(manager.clients.values())
        await manager.close()
    assert all(client.worker is None for client in clients)


async def test_remote_auth_failure_is_actionable_and_does_not_expose_secrets(remote_server, workdir):
    definition, _ = remote_server
    client = RemoteMCPClient('private', {**definition, 'headers': {'Authorization': 'Bearer wrong-secret'}}, workdir)
    with pytest.raises(ToolError, match='/mcp login private') as error:
        await client.connect()
    assert 'wrong-secret' not in str(error.value)
    assert client.worker is None


async def test_remote_network_grant_is_enforced(workdir):
    client = RemoteMCPClient('blocked', {'type': 'http', 'url': 'https://example.com/mcp',
                                       '_isolate_network': True}, workdir)
    with pytest.raises(ToolError, match='network access is disabled'):
        await client.connect()


async def test_private_token_storage_roundtrip_and_permissions():
    from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
    store = MCPSecrets('demo', 'https://example.com/mcp')
    await store.set_tokens(OAuthToken(access_token='secret', token_type='Bearer', refresh_token='refresh'))
    await store.set_client_info(OAuthClientInformationFull(client_id='client-id', redirect_uris=['http://127.0.0.1:1234/callback']))
    assert (await store.get_tokens()).refresh_token == 'refresh'
    assert (await store.get_client_info()).client_id == 'client-id'
    assert MCPSecrets('demo', 'https://other.example/mcp').read() == {}
    if os.name != 'nt':
        assert store.path.stat().st_mode & 0o777 == 0o600
        assert store.path.parent.stat().st_mode & 0o777 == 0o700
    store.delete()
    assert await store.get_tokens() is None


async def test_oauth_callback_requires_matching_state_and_path():
    login = OAuthLogin('demo', {'url': 'https://example.com/mcp'}, interactive=True)
    login.result = asyncio.get_running_loop().create_future()
    login.state = 'expected-state'
    for target, accepted in [('/callback?code=bad&state=wrong', False),
                             ('/other?code=bad&state=expected-state', False),
                             ('/callback?code=good&state=expected-state', True)]:
        reader = asyncio.StreamReader()
        reader.feed_data(f'GET {target} HTTP/1.1\r\nHost: localhost\r\n\r\n'.encode())
        reader.feed_eof()
        data = bytearray()

        async def noop():
            pass

        writer = SimpleNamespace(write=data.extend, drain=noop, close=lambda: None, wait_closed=noop)
        await login._callback(reader, writer)
        assert login.result.done() is accepted
        assert b'good' not in data
    assert await login._wait() == ('good', 'expected-state')


async def test_background_connection_never_opens_browser(monkeypatch):
    login = OAuthLogin('demo', {'url': 'https://example.com/mcp'})
    with pytest.raises(ToolError, match='/mcp login demo'):
        await login._redirect('https://example.com/authorize?state=state')


@pytest.mark.parametrize('browser_result', [True, False, OSError('no browser')])
async def test_login_displays_complete_copyable_link_even_if_browser_fails(monkeypatch, browser_result):
    from unittest.mock import Mock
    from eirene.ui.chat import NoticeBlock

    say = Mock()
    browser = Mock(side_effect=browser_result) if isinstance(browser_result, Exception) else Mock(return_value=browser_result)
    monkeypatch.setattr('eirene.core.mcp_auth.webbrowser.open', browser)
    login = OAuthLogin('demo', {'url': 'https://example.com/mcp'}, interactive=True, say=say)
    url = 'https://example.com/authorize?state=state&code_challenge=' + 'a' * 600
    await login._redirect(url)
    browser.assert_called_once_with(url)
    say.assert_any_call(url, markdown=True)
    notice = NoticeBlock(url, markdown=True)
    assert url in notice._Static__content.plain
    if browser_result is not True:
        assert say.call_args.args[1] == 'warn'


async def test_browser_oauth_pkce_persistence_and_refresh(remote_server, workdir, monkeypatch):
    import httpx
    definition, calls = remote_server
    opened = []

    def browser(url):
        query = parse_qs(urlsplit(url).query)
        assert query['code_challenge_method'] == ['S256']
        calls.append(('challenge', query['code_challenge'][0]))
        opened.append(url)
        response = httpx.get(query['redirect_uri'][0], params={'code': 'test-code', 'state': query['state'][0]})
        assert response.status_code == 200
        return True

    monkeypatch.setattr('eirene.core.mcp_auth.webbrowser.open', browser)
    client = RemoteMCPClient('oauth', {**definition, 'auth': 'oauth'}, workdir, interactive=True)
    try:
        assert len(await client.connect()) == 2
    finally:
        await client.close()
    store = MCPSecrets('oauth', definition['url'])
    assert store.read()['tokens']['refresh_token'] == 'test-refresh'
    assert store.read()['oauth_metadata']['token_endpoint'].endswith('/auth/token')
    assert calls.count('authorization_code') == 1
    store.update(expires_at=time.time() - 1)
    client = RemoteMCPClient('oauth', {**definition, 'auth': 'oauth'}, workdir)
    try:
        assert len(await client.connect()) == 2
        assert await client.call('echo', {'value': 'after-refresh'}) == 'remote:after-refresh'
    finally:
        await client.close()
    assert calls.count('refresh_token') == 1
    assert len(opened) == 1


async def test_static_oauth_client_and_custom_authorization_parameters(remote_server, workdir, monkeypatch):
    import httpx
    definition, calls = remote_server

    def browser(url):
        query = parse_qs(urlsplit(url).query)
        assert query['client_id'] == ['pre-registered-client']
        assert query['access_type'] == ['offline']
        assert query['prompt'] == ['consent']
        calls.append(('challenge', query['code_challenge'][0]))
        response = httpx.get(query['redirect_uri'][0], params={'code': 'test-code', 'state': query['state'][0]})
        assert response.status_code == 200
        return True

    monkeypatch.setattr('eirene.core.mcp_auth.webbrowser.open', browser)
    client = RemoteMCPClient('static', {**definition, 'oauth': {
        'client_id': 'pre-registered-client', 'client_secret': 'private-client-secret',
        'authorization_params': {'access_type': 'offline', 'prompt': 'consent'}}}, workdir, interactive=True)
    try:
        assert len(await client.connect()) == 2
    finally:
        await client.close()
    assert 'registration' not in calls
    assert calls.count('authorization_code') == 1


async def test_native_provider_proxy_uses_saved_login(remote_server, workdir, config):
    from eirene.core.mcp_proxy import proxy_definition
    from eirene.core.mcp import MCPClient
    definition, _ = remote_server
    config.set('mcp_servers', {'remote': {**definition, 'network': True}})
    config.set('mcp_enabled', {'remote': True})
    config.save()
    MCPSecrets('remote', definition['url']).update(headers={'Authorization': 'Bearer test-secret'})
    proxy = proxy_definition('remote')
    if binary := os.environ.get('EIRENE_TEST_MCP_BINARY'):
        proxy['command'] = binary
        proxy['args'] = ['--mcp-proxy', 'remote']
    client = MCPClient('bridge', {**proxy, 'command': [proxy['command'], *proxy['args']]}, workdir)
    try:
        tools = await client.connect()
        assert {tool.remote_name for tool in tools} == {'echo', 'fail'}
        assert await client.call('echo', {'value': 'native'}) == 'remote:native'
        assert 'test-secret' not in json.dumps(proxy)
    finally:
        await client.close()
