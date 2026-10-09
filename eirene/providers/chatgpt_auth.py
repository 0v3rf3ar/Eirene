"""Public-client OAuth for ChatGPT plan usage, independent of Codex."""

from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import json
import os
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

import httpx

from ..core import paths
from ..core.config import _atomic_write
from ..core.errors import AuthError, ConfigError, ProviderError
from .base import Provider, wrap_transport_error

ISSUER = "https://auth.openai.com"
AUTHORIZE = ISSUER + "/api/accounts/authorize"
TOKEN = ISSUER + "/api/accounts/oauth/token"
RESOURCE = "https://api.openai.com/v1"
PLAN_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + PLAN_SCOPE


class ChatGPTAuth(Provider):
    """Protected account records and a loopback authorization transaction."""

    def __init__(self, *, timeout=300.0):
        super().__init__(None, RESOURCE, timeout=timeout)
        self.path = paths.home() / "chatgpt" / "auth.json"
        self._server = None
        self._pending = None

    def _read(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"accounts": {}, "active": ""}
        except (OSError, ValueError) as exc:
            raise AuthError("cannot read ChatGPT credentials; reconnect with /connect chatgpt-plan") from exc
        if not isinstance(data, dict) or not isinstance(data.get("accounts"), dict):
            raise AuthError("invalid ChatGPT credential file")
        return data

    def _save(self, data):
        try:
            _atomic_write(self.path, data)
        except ConfigError as exc:
            raise AuthError("cannot securely save ChatGPT credentials") from exc

    @asynccontextmanager
    async def _locked(self):
        """Serialize rotating refresh tokens across providers and processes."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        paths._tighten(self.path.parent)
        fd = os.open(self.path.with_suffix(".lock"), os.O_CREAT | os.O_RDWR, 0o600)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
            else:
                import fcntl
            deadline = time.monotonic() + 60
            while not acquired:
                try:
                    if os.name == "nt":
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise AuthError("another Eirene process is updating ChatGPT credentials; try again")
                    await asyncio.sleep(.1)
            yield
        finally:
            if acquired:
                if os.name == "nt":
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def accounts(self):
        data = self._read()
        return [(key, record.get("email") or record.get("subject") or key,
                 key == data.get("active")) for key, record in data["accounts"].items()]

    def account(self):
        data = self._read()
        return data["accounts"].get(data.get("active"), {})

    async def select(self, key):
        async with self._locked():
            data = self._read()
            if key not in data["accounts"]:
                raise AuthError("ChatGPT account is no longer saved")
            data["active"] = key
            self._save(data)

    async def login(self, key=""):
        await self.close()
        async with self._locked():
            data = self._read()
            data.setdefault("host_id", "urn:uuid:" + str(uuid.uuid4()))
            self._save(data)
            previous = data["accounts"].get(key, {})
        loop = asyncio.get_running_loop()
        pending = {"state": secrets.token_urlsafe(32), "nonce": secrets.token_urlsafe(32),
                   "verifier": secrets.token_urlsafe(64), "future": loop.create_future(),
                   "previous": previous, "host_id": data["host_id"]}
        self._pending = pending
        try:
            self._server = await asyncio.start_server(self._callback, "127.0.0.1", 0)
        except OSError as exc:
            self._pending = None
            raise AuthError("cannot start the local ChatGPT sign-in callback") from exc
        port = self._server.sockets[0].getsockname()[1]
        pending["redirect_uri"] = f"http://127.0.0.1:{port}/auth/callback"
        params = {"client_id": previous.get("client_id") or "dynamic_agent_client",
                  "ext_agent_host_id": data["host_id"], "response_type": "code",
                  "redirect_uri": pending["redirect_uri"], "scope": SCOPES,
                  "resource": RESOURCE, "state": pending["state"], "nonce": pending["nonce"],
                  "code_challenge_method": "S256",
                  "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(
                      pending["verifier"].encode()).digest()).decode().rstrip("=")}
        if previous:
            # Do not put retained ID tokens in URLs displayed in chat/session logs.
            if previous.get("email"):
                params["login_hint"] = previous["email"]
        else:
            params["agent_name_hint"] = "Eirene"
        return AUTHORIZE + "?" + urlencode(params)

    async def _callback(self, reader, writer):
        status, text = "400 Bad Request", "Invalid sign-in callback."
        try:
            line = await asyncio.wait_for(reader.readline(), 5)
            if len(line) > 8192:
                return
            parts = line.decode("ascii").strip().split()
            pending = self._pending
            if len(parts) == 3 and parts[0] == "GET" and pending:
                target = urlsplit(parts[1])
                query = parse_qs(target.query)
                state = query.get("state", [""])[0]
                if (target.path == "/auth/callback" and len(query.get("state", [])) == 1
                        and all(len(query.get(field, [])) <= 1 for field in ("code", "client_id", "error"))
                        and secrets.compare_digest(state, pending["state"])
                        and not pending["future"].done()):
                    pending["future"].set_result(query)
                    status, text = "200 OK", "Sign-in received. Return to Eirene to finish connecting."
            body = text.encode()
            writer.write((f"HTTP/1.1 {status}\r\nContent-Type: text/plain; charset=utf-8\r\n"
                          f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\n"
                          "Connection: close\r\n\r\n").encode() + body)
            await writer.drain()
        except (OSError, ValueError, asyncio.TimeoutError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    async def wait_for_login(self, timeout=300):
        pending = self._pending
        if not pending:
            raise AuthError("start ChatGPT sign-in first")
        try:
            query = await asyncio.wait_for(pending["future"], timeout)
            if query.get("error"):
                raise AuthError("ChatGPT sign-in was declined; grant plan usage to connect")
            code = query.get("code", [""])[0]
            previous = pending["previous"]
            client_id = query.get("client_id", [previous.get("client_id", "")])[0]
            if (not code or not client_id or client_id == "dynamic_agent_client"
                    or (previous and client_id != previous["client_id"])):
                raise AuthError("ChatGPT registration returned an invalid client ID or code")
            tokens = await self._token({"grant_type": "authorization_code", "client_id": client_id,
                                        "code": code, "code_verifier": pending["verifier"],
                                        "redirect_uri": pending["redirect_uri"], "resource": RESOURCE})
            identity = await self._identity(tokens.get("id_token", ""), client_id, pending["nonce"])
            if previous and identity["sub"] != previous["subject"]:
                raise AuthError("sign-in returned a different ChatGPT account")
            record = self._record(tokens, {"client_id": client_id, "subject": identity["sub"],
                                          "email": identity.get("email", ""), "issuer": ISSUER})
            async with self._locked():
                data = self._read()
                data["accounts"][client_id] = record
                data["active"] = client_id
                self._save(data)
            return record
        except asyncio.TimeoutError as exc:
            raise AuthError("ChatGPT sign-in timed out; run /connect chatgpt-plan again") from exc
        finally:
            await self.close()

    async def _identity(self, token, client_id, nonce):
        import jwt
        try:
            async with self._client() as client:
                response = await client.get(ISSUER + "/.well-known/jwks.json")
                response.raise_for_status()
                header = jwt.get_unverified_header(token)
                if header.get("alg") != "RS256":
                    raise AuthError("ChatGPT returned an unsupported ID-token signature")
                keys = response.json()["keys"]
                key = next(k for k in keys if k.get("kid") == header.get("kid"))
                identity = jwt.decode(token, jwt.PyJWK.from_dict(key).key, algorithms=["RS256"],
                                      audience=client_id, issuer=ISSUER, leeway=5,
                                      options={"require": ["sub", "exp", "iat", "nonce"]})
                if (not isinstance(identity["sub"], str) or not identity["sub"]
                        or not secrets.compare_digest(str(identity["nonce"]), nonce)):
                    raise AuthError("ChatGPT identity did not match this sign-in")
                return identity
        except httpx.HTTPError as exc:
            raise AuthError("could not verify ChatGPT identity; try signing in again") from exc
        except (jwt.PyJWTError, ValueError, KeyError, StopIteration, TypeError) as exc:
            raise AuthError("ChatGPT ID-token verification failed") from exc

    async def _token(self, form):
        try:
            async with self._client() as client:
                response = await client.post(TOKEN, data=form)
                if response.status_code >= 400:
                    # OAuth responses may contain credentials: never echo their bodies.
                    if response.status_code < 500:
                        raise AuthError("ChatGPT authorization expired or was rejected; reconnect with /connect chatgpt-plan")
                    raise ProviderError("ChatGPT sign-in service is temporarily unavailable", retryable=True)
                value = response.json()
                if not isinstance(value, dict):
                    raise ValueError()
                return value
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, "ChatGPT sign-in") from exc
        except ValueError as exc:
            raise AuthError("ChatGPT returned an invalid token response") from exc

    def _record(self, tokens, previous):
        scopes = str(tokens.get("scope", "")).split()
        if PLAN_SCOPE not in scopes or "resource.invoke" not in scopes:
            raise AuthError("ChatGPT plan usage was not authorized; reconnect and grant plan access")
        if (not tokens.get("access_token") or not tokens.get("refresh_token")
                or str(tokens.get("token_type", "")).lower() != "bearer"):
            raise AuthError("ChatGPT returned incomplete credentials")
        try:
            lifetime = int(tokens["expires_in"])
            if lifetime <= 0:
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthError("ChatGPT returned invalid token expiry") from exc
        return {**previous, "access_token": tokens["access_token"],
                "refresh_token": tokens["refresh_token"],
                "id_token": tokens.get("id_token") or previous.get("id_token", ""),
                "scopes": scopes, "expires_at": time.time() + lifetime}

    async def access_token(self):
        async with self._locked():
            data = self._read()
            key = data.get("active")
            record = data["accounts"].get(key, {})
            if not record.get("refresh_token") or PLAN_SCOPE not in record.get("scopes", []):
                raise AuthError("sign in with /connect chatgpt-plan first")
            if record.get("access_token") and record.get("expires_at", 0) > time.time() + 30:
                return record["access_token"]
            tokens = await self._token({"grant_type": "refresh_token", "client_id": record["client_id"],
                                        "refresh_token": record["refresh_token"], "resource": RESOURCE})
            # A refresh may omit scope, retaining the existing grant.
            tokens.setdefault("scope", " ".join(record["scopes"]))
            record = self._record(tokens, record)
            data["accounts"][key] = record
            self._save(data)
            return record["access_token"]

    async def logout(self):
        confirmed = True
        async with self._locked():
            data = self._read()
            record = data["accounts"].get(data.get("active"), {})
            if record.get("refresh_token"):
                try:
                    async with self._client() as client:
                        discovery = await client.get(ISSUER + "/.well-known/openid-configuration")
                        discovery.raise_for_status()
                        endpoint = discovery.json()["revocation_endpoint"]
                        if not endpoint.startswith(ISSUER + "/"):
                            raise ValueError()
                        response = await client.post(endpoint, data={"token": record["refresh_token"],
                            "token_type_hint": "refresh_token", "client_id": record["client_id"]})
                        confirmed = response.status_code == 200
                except (httpx.HTTPError, ValueError, KeyError):
                    confirmed = False
            for field in ("access_token", "refresh_token", "id_token", "scopes", "expires_at"):
                record.pop(field, None)
            self._save(data)
        return confirmed

    async def close(self):
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._pending and not self._pending["future"].done():
            self._pending["future"].cancel()
        self._pending = None
