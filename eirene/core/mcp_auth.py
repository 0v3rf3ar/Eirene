"""Private per-server credentials and browser OAuth with the official MCP SDK."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import tempfile
import time
import webbrowser
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from . import paths
from .errors import ToolError


class MCPSecrets:
    def __init__(self, name: str, url: str):
        key = hashlib.sha256((name + '\n' + url).encode()).hexdigest()
        self.path = paths.home() / 'mcp-auth' / (key + '.json')

    def read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except FileNotFoundError:
            return {}

    def update(self, **changes) -> None:
        body = {**self.read(), **changes}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, filename = tempfile.mkstemp(dir=self.path.parent, prefix='.auth-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                json.dump(body, stream)
            os.replace(filename, self.path)
        finally:
            if os.path.exists(filename):
                os.unlink(filename)

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)

    async def get_tokens(self):
        from mcp.shared.auth import OAuthToken
        value = self.read().get('tokens')
        return OAuthToken.model_validate(value) if value else None

    async def set_tokens(self, tokens) -> None:
        extra = {}
        context = getattr(self, 'context', None)
        if context:
            extra = {
                'oauth_metadata': context.oauth_metadata.model_dump(mode='json') if context.oauth_metadata else None,
                'resource_metadata': context.protected_resource_metadata.model_dump(mode='json') if context.protected_resource_metadata else None,
                'auth_server_url': context.auth_server_url,
            }
        self.update(tokens=tokens.model_dump(mode='json'),
                    expires_at=time.time() + tokens.expires_in if tokens.expires_in is not None else None, **extra)

    async def get_client_info(self):
        from mcp.shared.auth import OAuthClientInformationFull
        value = self.read().get('client')
        return OAuthClientInformationFull.model_validate(value) if value else None

    async def set_client_info(self, client_info) -> None:
        self.update(client=client_info.model_dump(mode='json'))


class OAuthLogin:
    def __init__(self, name: str, definition: dict, *, interactive=False, say=None):
        self.name = name
        self.definition = definition
        self.storage = MCPSecrets(name, definition['url'])
        self.interactive = interactive
        self.say = say
        self.server = None
        self.result = None
        self.state = ''
        self.callback_path = '/callback'

    async def __aenter__(self):
        try:
            return await self._enter()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _enter(self):
        from mcp.client.auth import OAuthClientProvider
        from mcp.shared.auth import OAuthClientMetadata
        if not self.interactive and not self.storage.read().get('tokens'):
            raise ToolError(f'MCP {self.name} needs sign-in; run /mcp login {self.name}')
        settings = self.definition.get('oauth', {})
        redirect_uri = settings.get('redirect_uri')
        redirect = urlsplit(redirect_uri) if redirect_uri else None
        if redirect and (redirect.scheme != 'http' or redirect.hostname not in ('localhost', '127.0.0.1') or not redirect.port):
            raise ToolError('OAuth redirect_uri must be a registered localhost HTTP callback with a port')
        self.callback_path = redirect.path or '/callback' if redirect else '/callback'
        port = redirect.port if redirect else self.storage.read().get('port', 0)
        if self.interactive:
            self.result = asyncio.get_running_loop().create_future()
            try:
                self.server = await asyncio.start_server(self._callback, '127.0.0.1', port, limit=8192)
            except OSError as exc:
                raise ToolError('MCP sign-in callback port is busy; close the other sign-in and retry') from exc
            port = self.server.sockets[0].getsockname()[1]
            self.storage.update(port=port)
        metadata = OAuthClientMetadata(
            client_name='Eirene', redirect_uris=[redirect_uri or f'http://127.0.0.1:{port}/callback'],
            grant_types=['authorization_code', 'refresh_token'], response_types=['code'],
            token_endpoint_auth_method=settings.get('token_endpoint_auth_method', 'client_secret_post' if settings.get('client_secret') else 'none'),
            scope=settings.get('scope', self.definition.get('scope')))
        if settings.get('client_id'):
            from mcp.shared.auth import OAuthClientInformationFull
            saved_client = await self.storage.get_client_info()
            await self.storage.set_client_info(OAuthClientInformationFull(
                **metadata.model_dump(), client_id=settings['client_id'], client_secret=settings.get('client_secret'),
                issuer=saved_client.issuer if saved_client and saved_client.client_id == settings['client_id'] else None))
        provider = OAuthClientProvider(
            server_url=self.definition['url'], client_metadata=metadata, storage=self.storage,
            redirect_handler=self._redirect, callback_handler=self._wait,
            timeout=300, client_metadata_url=self.definition.get('client_metadata_url'))
        # The SDK owns discovery, PKCE, refresh, and issuer validation. Restore
        # its discovered endpoints and absolute expiry across process restarts.
        from mcp.shared.auth import OAuthMetadata, ProtectedResourceMetadata
        saved = self.storage.read()
        context = provider.context
        if saved.get('oauth_metadata'):
            context.oauth_metadata = OAuthMetadata.model_validate(saved['oauth_metadata'])
        if saved.get('resource_metadata'):
            context.protected_resource_metadata = ProtectedResourceMetadata.model_validate(saved['resource_metadata'])
        context.auth_server_url = saved.get('auth_server_url')
        context.token_expiry_time = saved.get('expires_at')
        self.storage.context = context
        return provider

    async def __aexit__(self, *args):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if self.result and not self.result.done():
            self.result.cancel()

    async def _redirect(self, url: str) -> None:
        if not self.interactive:
            raise ToolError(f'MCP {self.name} needs sign-in; run /mcp login {self.name}')
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        reserved = {'state', 'client_id', 'redirect_uri', 'response_type', 'code_challenge', 'code_challenge_method'}
        parameters = self.definition.get('oauth', {}).get('authorization_params', {})
        if not isinstance(parameters, dict) or reserved.intersection(parameters):
            raise ToolError('OAuth authorization_params cannot override state, PKCE, client ID, or redirect URI')
        query.update({key: [str(value)] for key, value in parameters.items()})
        url = urlunsplit(parsed._replace(query=urlencode(query, doseq=True)))
        self.state = query.get('state', [''])[0]
        if self.say:
            self.say('Sign in to ' + self.name + '. Click or copy this link into your browser:')
            self.say(url, markdown=True)
        try:
            opened = await asyncio.to_thread(webbrowser.open, url)
        except (webbrowser.Error, OSError):
            opened = False
        if not opened and self.say:
            self.say('Could not open your browser automatically; click the URL above or copy it into your browser.', 'warn')

    async def _wait(self):
        if self.result is None:
            raise ToolError(f'run /mcp login {self.name} to sign in')
        try:
            return await asyncio.wait_for(asyncio.shield(self.result), 300)
        except asyncio.TimeoutError as exc:
            raise ToolError('MCP sign-in timed out; retry from /mcp') from exc

    async def _callback(self, reader, writer) -> None:
        status, message = '400 Bad Request', 'Invalid sign-in callback. Return to Eirene and retry.'
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 5)
            method, target, _ = request.split(b'\r\n', 1)[0].decode('ascii').split(' ', 2)
            parsed = urlsplit(target)
            query = parse_qs(parsed.query)
            state = query.get('state', [''])[0]
            if (method == 'GET' and parsed.path == self.callback_path and self.state
                    and secrets.compare_digest(state, self.state) and not self.result.done()):
                if query.get('error'):
                    self.result.set_exception(ToolError('MCP sign-in was declined; retry when ready'))
                elif query.get('code'):
                    self.result.set_result((query['code'][0], state))
                    status, message = '200 OK', 'Sign-in received. You can return to Eirene.'
            payload = message.encode()
            writer.write((f'HTTP/1.1 {status}\r\nContent-Type: text/plain\r\n'
                          f'Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n').encode() + payload)
            await writer.drain()
        except (OSError, ValueError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
