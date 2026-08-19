"""Ollama native protocol."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from ..core.errors import ProviderError
from .base import (Done, Provider, TextDelta, ThinkingDelta, ToolCall, Usage,
                   parse_json, raise_for_status, wrap_transport_error)
from .local_profile import LocalProfile

DEFAULT_BASE = "https://ollama.com"


class Ollama(Provider):
    """Ollama's native protocol over HTTP."""

    name = "ollama"
    protocol = "ollama"

    def __init__(self, api_key=None, base_url=DEFAULT_BASE, *, name="ollama",
                 static_models=None, timeout=600.0, think: bool | None = None):
        super().__init__(api_key, base_url or DEFAULT_BASE, timeout=timeout)
        self.name = name
        self.static_models = list(static_models or [])
        self.think = think
        self.profile = LocalProfile.detect() if name == "ollama-local" else None
        self._model_details: dict[str, dict] = {}

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    def headers(self) -> dict[str, str]:
        head = {"Content-Type": "application/json"}
        if self.api_key:
            head["Authorization"] = f"Bearer {self.api_key}"
        return head

    async def stream(self, messages, model, *, system="", tools=None,
                     max_tokens=8192) -> AsyncIterator:
        if self.profile is not None:
            details = await self._details(model)
            self.profile = self.profile.with_model(model, details)
            system = self.profile.system(system)
            tools = self.profile.tools(tools)
            max_tokens = min(max_tokens, self.profile.max_tokens)
        payload: dict[str, Any] = {
            "model": model,
            "messages": to_ollama_messages(messages, system),
            "stream": True,
            "options": {"num_predict": max_tokens},
        }
        if self.profile is not None:
            payload["options"]["num_ctx"] = self.profile.context_tokens
        if self.think is not None:
            payload["think"] = self.think
        if tools:
            payload["tools"] = [{"type": "function", "function": spec} for spec in tools]
        calls: list[ToolCall] = []
        finish = "stop"
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self.base_url}/api/chat",
                                         json=payload, headers=self.headers()) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise_for_status(response, self.host, model)
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        chunk = parse_json(line)
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            raise ProviderError(str(chunk["error"])[:200])
                        for event in _consume(chunk, calls):
                            yield event
                        if chunk.get("done"):
                            finish = str(chunk.get("done_reason") or "stop")
                            break
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, self.host) from exc

        for call in calls:
            yield call
        yield Done("tool_use" if calls and finish != "length" else finish)

    async def _details(self, model: str) -> dict:
        """Fetch local model size once; model-name parsing remains the fallback."""
        if model in self._model_details:
            return self._model_details[model]
        details: dict = {}
        try:
            async with self._client() as client:
                response = await client.post(f"{self.base_url}/api/show",
                                             json={"model": model},
                                             headers=self.headers())
                if response.status_code < 400:
                    body = response.json()
                    if isinstance(body, dict) and isinstance(body.get("details"), dict):
                        details = body["details"]
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            pass
        self._model_details[model] = details
        return details

    async def models(self) -> list[str]:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/api/tags",
                                            headers=self.headers())
                raise_for_status(response, self.host)
                body = response.json()
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, self.host) from exc
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderError(f"{self.host} returned invalid JSON") from exc
        names = [str(item.get("name")) for item in body.get("models", [])
                 if isinstance(item, dict) and item.get("name")]
        if not names:
            if self.static_models:
                return list(self.static_models)
            raise ProviderError(f"{self.host} lists no models")
        return sorted(names)

    async def validate(self, model: str = "") -> str:
        try:
            names = await self.models()
        except ProviderError as exc:
            if exc.status != 404 or not self.static_models:
                raise
            names = self.static_models
        return f"{len(names)} models"


def _consume(chunk: dict, calls: list[ToolCall]) -> list:
    events = []
    message = chunk.get("message") or {}
    if isinstance(message, dict):
        thinking = message.get("thinking")
        if isinstance(thinking, str) and thinking:
            events.append(ThinkingDelta(thinking))
        content = message.get("content")
        if isinstance(content, str) and content:
            events.append(TextDelta(content))
        for call in message.get("tool_calls") or []:
            function = (call or {}).get("function") or {}
            name = function.get("name")
            if not name:
                continue
            args = function.get("arguments")
            if isinstance(args, str):
                args = parse_json(args) or {}
            calls.append(ToolCall(f"call_{len(calls)}", str(name),
                                  args if isinstance(args, dict) else {}))
    if chunk.get("done"):
        events.append(Usage(int(chunk.get("prompt_eval_count") or 0),
                            int(chunk.get("eval_count") or 0)))
    return events


def to_ollama_messages(messages: list[dict], system: str) -> list[dict]:
    """Convert internal history to Ollama messages."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        role = message.get("role")
        if role in ("user", "system"):
            out.append({"role": role, "content": message.get("content", "")})
        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant",
                                     "content": message.get("content") or ""}
            calls = message.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {"function": {"name": call["name"],
                                  "arguments": call.get("arguments") or {}}}
                    for call in calls]
            out.append(entry)
        elif role == "tool":
            out.append({"role": "tool", "content": message.get("content", ""),
                        "tool_name": message.get("name", "")})
    return out
