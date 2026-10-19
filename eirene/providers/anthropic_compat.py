"""Anthropic messages protocol."""

from __future__ import annotations

import copy
import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from .history import provider_history

from ..core.errors import ProviderError
from .base import (Done, Provider, TextDelta, ThinkingDelta, ToolCall, Usage,
                   loads_arguments, parse_json, raise_for_status, sse_lines,
                   wrap_transport_error)

API_VERSION = "2023-06-01"


class AnthropicCompatible(Provider):
    """Works for Claude and Anthropic-shaped clones."""

    protocol = "anthropic"

    def __init__(self, api_key, base_url, *, name="anthropic", static_models=(),
                 timeout=300.0, extra_headers=None):
        super().__init__(api_key, base_url, timeout=timeout)
        self.name = name
        self.static_models = list(static_models)
        self.extra_headers = dict(extra_headers or {})

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    def headers(self) -> dict[str, str]:
        head = {"Content-Type": "application/json", "anthropic-version": API_VERSION}
        if self.api_key:
            head["x-api-key"] = self.api_key
        head.update(self.extra_headers)
        return head

    async def stream(self, messages, model, *, system="", tools=None,
                     max_tokens=8192) -> AsyncIterator:
        from .preflight import validate_history
        validate_history(messages)
        payload: dict[str, Any] = {
            "model": model,
            "messages": to_anthropic_messages(messages),
            "max_tokens": max_tokens,
            "stream": True,
        }
        from .preflight import validate_anthropic
        validate_anthropic(payload["messages"])
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [{"name": spec["name"],
                                 "description": spec.get("description", ""),
                                 "input_schema": spec.get("parameters", {})}
                                for spec in tools]
        blocks: dict[int, dict[str, Any]] = {}
        stop = "stop"
        completed = False
        try:
            async with self._client() as client:
                async with client.stream("POST", f"{self.base_url}/messages",
                                         json=payload, headers=self.headers()) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise_for_status(response, self.host, model)
                    async for name, data in sse_lines(response):
                        chunk = parse_json(data)
                        if not isinstance(chunk, dict):
                            continue
                        kind = chunk.get("type") or name
                        if kind == "error":
                            detail = chunk.get("error") or {}
                            raise ProviderError(str(detail.get("message") or detail)[:200])
                        for event in _consume(kind, chunk, blocks):
                            yield event
                        if kind == "message_delta":
                            stop = (chunk.get("delta") or {}).get("stop_reason") or stop
                        elif kind == "message_stop":
                            completed = True
                            break
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, self.host) from exc

        if not completed:
            raise ProviderError("model response ended before completion; no tools were executed", retryable=True)
        calls = _flush(blocks)
        for call in calls:
            yield call
        content = []
        for index in sorted(blocks):
            slot = blocks[index]
            block = copy.deepcopy(slot["block"])
            if block.get("type") == "tool_use" and slot.get("json"):
                block["input"] = loads_arguments(slot["json"])
            content.append(block)
        yield Done("tool_use" if calls and stop != "max_tokens" else stop,
                   anthropic_blocks=content or None)

    async def models(self) -> list[str]:
        try:
            async with self._client() as client:
                names, seen = [], set()
                params = {"limit": 100}
                while True:
                    response = await client.get(f"{self.base_url}/models",
                                                headers=self.headers(), params=params)
                    if response.status_code in (401, 403):
                        raise_for_status(response, self.host)
                    if response.status_code >= 400:
                        break
                    body = response.json()
                    names.extend(str(item["id"]) for item in body.get("data", [])
                                 if isinstance(item, dict) and item.get("id"))
                    token = body.get("last_id") if body.get("has_more") else None
                    if not token or token in seen:
                        break
                    seen.add(token)
                    params["after_id"] = token
                if names:
                    return sorted(set(names), reverse=True)
        except httpx.HTTPError as exc:
            if not self.static_models:
                raise wrap_transport_error(exc, self.host) from exc
        except (json.JSONDecodeError, ValueError):
            pass
        if self.static_models:
            return list(self.static_models)
        raise ProviderError(f"{self.host} did not return a model list")


def _consume(kind: str, chunk: dict, blocks: dict[int, dict]) -> list:
    events = []
    if kind == "message_start":
        usage = ((chunk.get("message") or {}).get("usage")) or {}
        events.append(Usage(int(usage.get("input_tokens") or 0),
                            int(usage.get("output_tokens") or 0)))
    elif kind == "content_block_start":
        index = int(chunk.get("index") or 0)
        block = chunk.get("content_block") or {}
        blocks[index] = {"type": block.get("type", "text"), "id": block.get("id", ""),
                         "name": block.get("name", ""), "json": "", "block": copy.deepcopy(block)}
        if block.get("type") == "text" and block.get("text"):
            events.append(TextDelta(block["text"]))
    elif kind == "content_block_delta":
        index = int(chunk.get("index") or 0)
        delta = chunk.get("delta") or {}
        dtype = delta.get("type")
        slot = blocks.get(index)
        field = {"text_delta": "text", "thinking_delta": "thinking", "signature_delta": "signature"}.get(dtype)
        if slot and field:
            block = slot["block"]
            block[field] = block.get(field, "") + str(delta.get(field, ""))
        if dtype == "text_delta":
            events.append(TextDelta(str(delta.get("text", ""))))
        elif dtype == "thinking_delta":
            events.append(ThinkingDelta(str(delta.get("thinking", ""))))
        elif dtype == "input_json_delta":
            slot = blocks.setdefault(index, {"type": "tool_use", "id": "",
                                             "name": "", "json": "", "block": {"type": "tool_use"}})
            slot["json"] += str(delta.get("partial_json", ""))
    elif kind == "message_delta":
        usage = chunk.get("usage") or {}
        if usage:
            events.append(Usage(int(usage.get("input_tokens") or 0),
                                int(usage.get("output_tokens") or 0)))
    return events


def _flush(blocks: dict[int, dict]) -> list[ToolCall]:
    calls = []
    for index in sorted(blocks):
        slot = blocks[index]
        if slot.get("type") != "tool_use" or not slot.get("name"):
            continue
        calls.append(ToolCall(slot.get("id") or f"call_{index}", slot["name"],
                              loads_arguments(slot["json"]) if slot.get("json") else
                              slot.get("block", {}).get("input", {})))
    return calls


def to_anthropic_messages(messages: list[dict]) -> list[dict]:
    """Convert internal history to Anthropic blocks."""
    out: list[dict] = []
    for message in provider_history(messages):
        role = message.get("role")
        if role in ("user", "system"):
            blocks = [{"type": "text", "text": message.get("content", "")}]
            for item in message.get("attachments") or []:
                blocks.append({"type": "image", "source": {"type": "base64",
                              "media_type": item.get("mime_type"),
                              "data": item.get("data")}})
            _append(out, "user", blocks)
        elif role == "assistant":
            if message.get("anthropic_blocks"):
                out.append({"role": "assistant", "content": copy.deepcopy(message["anthropic_blocks"])})
                continue
            content: list[dict] = []
            text = message.get("content") or ""
            if text:
                content.append({"type": "text", "text": text})
            for call in message.get("tool_calls") or []:
                content.append({"type": "tool_use", "id": call["id"],
                                "name": call["name"], "input": call.get("arguments") or {}})
            if content:
                out.append({"role": "assistant", "content": content})
        elif role == "tool":
            _append(out, "user", [{"type": "tool_result",
                                   "tool_use_id": message.get("tool_call_id", ""),
                                   "content": message.get("content", "") or "(no output)",
                                   "is_error": bool(message.get("is_error"))}])
    return out


def _append(out: list[dict], role: str, blocks: list[dict]) -> None:
    """Merge into the previous same-role message."""
    if out and out[-1]["role"] == role and isinstance(out[-1]["content"], list):
        out[-1]["content"].extend(blocks)
    else:
        out.append({"role": role, "content": blocks})
