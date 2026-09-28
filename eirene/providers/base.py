"""Normalised provider interface."""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from ..core.errors import (AuthError, ConnectionFailed, ModelNotFound, ProviderError,
                           RateLimitError)


@dataclass
class ConnectionStatus:
    text: str


@dataclass
class TextDelta:
    text: str


@dataclass
class ThinkingDelta:
    text: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(self.input_tokens + other.input_tokens,
                     self.output_tokens + other.output_tokens)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class PlanUpdate:
    steps: list[dict[str, str]] = field(default_factory=list)
    explanation: str = ""


@dataclass
class ProviderTool:
    """A tool the provider ran itself. Eirene shows it and never runs it."""

    id: str
    name: str
    label: str = ""
    kind: str = "exec"
    result: str = ""
    finished: bool = False
    is_error: bool = False
    preview: str = ""


@dataclass
class Done:
    reason: str = "stop"


Event = (TextDelta | ThinkingDelta | ToolCall | Usage | PlanUpdate
         | ProviderTool | ConnectionStatus | Done)


class Provider:
    """One API backend."""

    name = ""
    protocol = ""
    supports_tools = True
    # True for CLIs that run their own agent loop, prompt and sandbox. Eirene
    # is their front end: it sends no instructions of its own beyond skills.
    owns_context = False

    def __init__(self, api_key: str | None, base_url: str, *, timeout: float = 300.0):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def headers(self) -> dict[str, str]:
        return {"Content-Type": "application/json"}

    def _client(self) -> httpx.AsyncClient:
        limits = httpx.Limits(max_connections=8, max_keepalive_connections=4)
        return httpx.AsyncClient(timeout=httpx.Timeout(self.timeout, connect=20.0),
                                 limits=limits, follow_redirects=True,
                                 transport=_TRANSPORT)

    async def stream(self, messages: list[dict], model: str, *, system: str = "",
                     tools: list[dict] | None = None,
                     max_tokens: int = 8192) -> AsyncIterator[Event]:
        raise NotImplementedError

    async def models(self) -> list[str]:
        raise NotImplementedError

    async def validate(self, model: str = "") -> str:
        """Cheap credential check; returns a note."""
        names = await self.models()
        return f"{len(names)} models available"


_TRANSPORT: httpx.AsyncBaseTransport | None = None


def set_transport(transport: httpx.AsyncBaseTransport | None) -> None:
    """Inject a transport, used by tests."""
    global _TRANSPORT
    _TRANSPORT = transport


def raise_for_status(response: httpx.Response, host: str, model: str = "") -> None:
    """Map an HTTP error to a typed error."""
    code = response.status_code
    if code < 400:
        return
    detail = _error_detail(response)
    if code in (401, 403):
        raise AuthError(f"API key rejected by {host}" + (f": {detail}" if detail else ""))
    if code == 404:
        if model:
            raise ModelNotFound(model)
        raise ProviderError(f"{host} returned 404" + (f": {detail}" if detail else ""),
                            status=404)
    if code == 429:
        try:
            error = response.json().get("error", {})
            error_code = error.get("code", "") if isinstance(error, dict) else ""
        except (ValueError, AttributeError):
            error_code = ""
        if error_code in {"insufficient_quota", "billing_hard_limit_reached", "organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"}:
            raise ProviderError(f"{host}: {detail or error_code}", status=code)
        retry = _retry_after(response)
        note = f"rate limited by {host}"
        if retry:
            note += f", retry in {retry:.0f}s"
        raise RateLimitError(note, retry_after=retry)
    if code >= 500 or code == 408:
        error = ProviderError(explain(code, host, detail, model), retryable=True, status=code)
        error.retry_after = _retry_after(response)
        raise error
    raise ProviderError(explain(code, host, detail, model), status=code)


DETAIL_LIMIT = 160
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f\u21b5]")
_QUOTED = re.compile(r'"(?:message|error|detail|msg)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_UNTERMINATED = re.compile(r'"(?:message|error|detail|msg)"\s*:\s*"')

TEMPLATE_MARKERS = ("raise_exception", "chat template", "jinja",
                    "no user query", "template:")
MEMORY_MARKERS = ("out of memory", "system memory", "not enough memory",
                  "cuda error", "oom")


def tidy_detail(text: str, limit: int = DETAIL_LIMIT) -> str:
    """Reduce a provider error body to one readable line."""
    body = _ANSI.sub(" ", str(text or ""))
    for escape, plain in ((r"\n", " "), (r"\r", " "), (r"\t", " "),
                          (r"\"", '"'), ("\\\\", "\\")):
        body = body.replace(escape, plain)
    body = _CONTROL.sub(" ", body)
    body = " ".join(body.split()).strip(" -{}\"\\")
    if len(body) <= limit:
        return body
    return body[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"


def explain(code: int, host: str, detail: str, model: str = "") -> str:
    """Say what went wrong in words a user can act on."""
    lowered = (detail or "").lower()
    named = f"'{model}'" if model else "this model"
    if any(marker in lowered for marker in TEMPLATE_MARKERS):
        return (f"{named} cannot handle this conversation: its chat template "
                "rejected the tool results Eirene sent. Pick another model with "
                "/model, ideally one built for tool use.")
    if any(marker in lowered for marker in MEMORY_MARKERS):
        return (f"{named} needs more memory than {host} has free. Try a smaller "
                "model with /model, or close other programs.")
    if code >= 500:
        base = f"{host} failed while answering (error {code})"
        return f"{base}: {detail}" if detail else f"{base}; try again."
    base = f"{host} rejected the request ({code})"
    return f"{base}: {detail}" if detail else base


def _salvage(text: str) -> str:
    """Pull a message out of a body that would not parse as JSON."""
    body = text or ""
    found = [match.group(1) for match in _QUOTED.finditer(body)]
    if found:
        return max(found, key=len)
    opened = list(_UNTERMINATED.finditer(body))
    return body[opened[-1].end():] if opened else body


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError, UnicodeDecodeError):
        return tidy_detail(_salvage(response.text or ""))
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            return tidy_detail(error.get("message") or error.get("type") or "")
        if isinstance(error, str):
            return tidy_detail(error)
        for key in ("message", "detail", "msg"):
            if key in body:
                return tidy_detail(body[key])
    return ""


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            seconds = (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def wrap_transport_error(exc: Exception, host: str) -> ProviderError:
    if isinstance(exc, httpx.TimeoutException):
        return ProviderError(f"{host} timed out", retryable=True)
    return ConnectionFailed(host, str(exc)[:120])


async def sse_lines(response: httpx.Response) -> AsyncIterator[tuple[str, str]]:
    """Yield (event, data) pairs from an SSE body."""
    event = ""
    async for raw in response.aiter_lines():
        line = raw.rstrip("\r")
        if not line:
            event = ""
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
            continue
        if line.startswith("data:"):
            yield event, line[5:].strip()


def parse_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def loads_arguments(raw: str) -> dict[str, Any]:
    """Tolerant tool-argument decoding."""
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        repaired = raw.strip()
        for suffix in ("}", '"}', '"}]'):
            try:
                value = json.loads(repaired + suffix)
                break
            except (json.JSONDecodeError, ValueError):
                continue
        else:
            raise ProviderError("model returned malformed tool arguments")
    return value if isinstance(value, dict) else {"value": value}


async def with_retries(factory, attempts: int = 3, on_retry=None):
    """Retry a request coroutine on transient errors."""
    delay = 1.0
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return await factory()
        except ProviderError as exc:
            last = exc
            if not exc.retryable or attempt == attempts - 1:
                raise
            wait = getattr(exc, "retry_after", None) or delay
            if on_retry:
                on_retry(exc, wait)
            await asyncio.sleep(min(wait, 30))
            delay *= 2
    raise last if last else ProviderError("request failed")
