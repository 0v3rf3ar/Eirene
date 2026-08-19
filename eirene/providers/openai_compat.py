"""OpenAI chat-completions protocol."""

from __future__ import annotations

import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from ..core.errors import ProviderError
from .base import (Done, Provider, TextDelta, ThinkingDelta, ToolCall, Usage,
                   loads_arguments, parse_json, raise_for_status, sse_lines,
                   wrap_transport_error)


class OpenAICompatible(Provider):
    """Works for OpenAI, DeepSeek, Kimi, Perplexity and clones."""

    protocol = "openai"

    def __init__(self, api_key, base_url, *, name="openai", supports_tools=True,
                 static_models=(), timeout=300.0, extra_headers=None):
        super().__init__(api_key, base_url, timeout=timeout)
        self.name = name
        self.supports_tools = supports_tools
        self.static_models = list(static_models)
        self.extra_headers = dict(extra_headers or {})

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    def headers(self) -> dict[str, str]:
        head = {"Content-Type": "application/json"}
        if self.api_key:
            head["Authorization"] = f"Bearer {self.api_key}"
        head.update(self.extra_headers)
        return head

    def _body(self, messages, model, system, tools, max_tokens) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": to_openai_messages(messages, system),
            "stream": True,
            "max_tokens": max_tokens,
        }
        if tools and self.supports_tools:
            payload["tools"] = [{"type": "function", "function": spec} for spec in tools]
            payload["tool_choice"] = "auto"
        if self.host.endswith("openai.com") or self.host.endswith("deepseek.com"):
            payload["stream_options"] = {"include_usage": True}
        return payload

    async def stream(self, messages, model, *, system="", tools=None,
                     max_tokens=8192) -> AsyncIterator:
        payload = self._body(messages, model, system, tools, max_tokens)
        url = f"{self.base_url}/chat/completions"
        pending: dict[int, dict[str, Any]] = {}
        finish = "stop"
        try:
            async with self._client() as client:
                async with client.stream("POST", url, json=payload,
                                         headers=self.headers()) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise_for_status(response, self.host, model)
                    async for _, data in sse_lines(response):
                        if data == "[DONE]":
                            break
                        chunk = parse_json(data)
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            raise ProviderError(str(chunk["error"])[:200])
                        for event in _consume(chunk, pending):
                            yield event
                        reason = _finish_reason(chunk)
                        if reason:
                            finish = reason
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, self.host) from exc

        for call in _flush(pending):
            yield call
        yield Done("tool_use" if pending else finish)

    async def models(self) -> list[str]:
        if not self.static_models or self.api_key:
            try:
                async with self._client() as client:
                    response = await client.get(f"{self.base_url}/models",
                                                headers=self.headers())
                    if response.status_code < 400:
                        names = _model_names(response.json())
                        if names:
                            return names
                    elif response.status_code in (401, 403):
                        raise_for_status(response, self.host)
            except httpx.HTTPError as exc:
                if not self.static_models:
                    raise wrap_transport_error(exc, self.host) from exc
            except (json.JSONDecodeError, ValueError):
                pass
        if self.static_models:
            return list(self.static_models)
        raise ProviderError(f"{self.host} did not return a model list")


def _model_names(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    items = body.get("data") or body.get("models") or []
    names = []
    for item in items:
        if isinstance(item, dict):
            name = item.get("id") or item.get("name")
            if name:
                names.append(str(name))
        elif isinstance(item, str):
            names.append(item)
    return sorted(set(names))


def _finish_reason(chunk: dict) -> str:
    choices = chunk.get("choices") or []
    if choices and isinstance(choices[0], dict):
        return choices[0].get("finish_reason") or ""
    return ""


def _consume(chunk: dict, pending: dict[int, dict]) -> list:
    events = []
    usage = chunk.get("usage")
    if isinstance(usage, dict):
        events.append(Usage(int(usage.get("prompt_tokens") or 0),
                            int(usage.get("completion_tokens") or 0)))
    choices = chunk.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return events
    delta = choices[0].get("delta") or {}
    if not isinstance(delta, dict):
        return events
    thinking = delta.get("reasoning_content") or delta.get("reasoning")
    if isinstance(thinking, str) and thinking:
        events.append(ThinkingDelta(thinking))
    content = delta.get("content")
    if isinstance(content, str) and content:
        events.append(TextDelta(content))
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                events.append(TextDelta(str(part.get("text", ""))))
    for call in delta.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        index = int(call.get("index") or 0)
        slot = pending.setdefault(index, {"id": "", "name": "", "args": ""})
        if call.get("id"):
            slot["id"] = str(call["id"])
        function = call.get("function") or {}
        if function.get("name"):
            slot["name"] = str(function["name"])
        if function.get("arguments"):
            slot["args"] += str(function["arguments"])
    return events


def _flush(pending: dict[int, dict]) -> list[ToolCall]:
    calls = []
    for index in sorted(pending):
        slot = pending[index]
        if not slot["name"]:
            continue
        calls.append(ToolCall(slot["id"] or f"call_{index}", slot["name"],
                              loads_arguments(slot["args"])))
    return calls


def to_openai_messages(messages: list[dict], system: str) -> list[dict]:
    """Convert internal history to the OpenAI shape."""
    out: list[dict] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        role = message.get("role")
        if role == "user":
            content = message.get("content", "")
            attachments = message.get("attachments") or []
            if attachments:
                content = ([{"type": "text", "text": content}] +
                           [{"type": "image_url", "image_url": {"url":
                             f"data:{item.get('mime_type')};base64,{item.get('data')}"}}
                            for item in attachments])
            out.append({"role": "user", "content": content})
        elif role == "system":
            out.append({"role": "system", "content": message.get("content", "")})
        elif role == "assistant":
            entry: dict[str, Any] = {"role": "assistant",
                                     "content": message.get("content") or ""}
            calls = message.get("tool_calls") or []
            if calls:
                entry["tool_calls"] = [
                    {"id": call["id"], "type": "function",
                     "function": {"name": call["name"],
                                  "arguments": json.dumps(call.get("arguments") or {})}}
                    for call in calls]
                if not entry["content"]:
                    entry["content"] = None
            out.append(entry)
        elif role == "tool":
            out.append({"role": "tool", "tool_call_id": message.get("tool_call_id", ""),
                        "content": message.get("content", "")})
    return out
