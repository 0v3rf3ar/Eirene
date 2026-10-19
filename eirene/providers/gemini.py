"""Google Gemini generateContent protocol."""

from __future__ import annotations

import copy
import json
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from .history import provider_history

from ..core.errors import ProviderError
from .base import (Done, Provider, TextDelta, ThinkingDelta, ToolCall, Usage,
                   parse_json, raise_for_status, sse_lines, wrap_transport_error)

DEFAULT_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Google's documented sentinel for client-generated calls or imported history.
# Real Gemini response parts must instead retain their original signatures.
CLIENT_CALL_SIGNATURE = "skip_thought_signature_validator"
SCHEMA_KEYS = {"type", "description", "properties", "required", "items", "enum", "format"}


class Gemini(Provider):
    """Google AI Studio endpoint."""

    name = "gemini"
    protocol = "gemini"

    def __init__(self, api_key, base_url=DEFAULT_BASE, *, static_models=(), timeout=300.0):
        super().__init__(api_key, base_url or DEFAULT_BASE, timeout=timeout)
        self.static_models = list(static_models)

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    def headers(self) -> dict[str, str]:
        head = {"Content-Type": "application/json"}
        if self.api_key:
            head["x-goog-api-key"] = self.api_key
        return head

    async def stream(self, messages, model, *, system="", tools=None,
                     max_tokens=8192) -> AsyncIterator:
        from .preflight import validate_history
        validate_history(messages)
        payload: dict[str, Any] = {
            "contents": to_gemini_contents(messages),
            "generationConfig": {"maxOutputTokens": max_tokens},
        }
        from .preflight import validate_gemini
        validate_gemini(payload["contents"], model)
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [_declaration(s) for s in tools]}]
        url = f"{self.base_url}/models/{model}:streamGenerateContent"
        calls: list[ToolCall] = []
        parts: list[dict] = []
        finish = "stop"
        completed = False
        try:
            async with self._client() as client:
                async with client.stream("POST", url, json=payload, params={"alt": "sse"},
                                         headers=self.headers()) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise_for_status(response, self.host, model)
                    async for _, data in sse_lines(response):
                        chunk = parse_json(data)
                        if not isinstance(chunk, dict):
                            continue
                        if chunk.get("error"):
                            detail = chunk["error"]
                            message = detail.get("message") if isinstance(detail, dict) else detail
                            raise ProviderError(str(message)[:200])
                        for event in _consume(chunk, calls, parts):
                            yield event
                        reason = _finish(chunk)
                        if reason:
                            finish = reason
                            completed = True
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, self.host) from exc

        if not completed:
            raise ProviderError("model response ended before completion; no tools were executed", retryable=True)
        for call in (calls if finish in {"STOP", "MAX_TOKENS"} else []):
            yield call
        reason = finish.lower()
        yield Done("tool_use" if calls and reason == "stop" else reason, gemini_parts=parts or None)

    async def models(self) -> list[str]:
        try:
            async with self._client() as client:
                names, seen = [], set()
                params = {"pageSize": 200}
                while True:
                    response = await client.get(f"{self.base_url}/models",
                                                headers=self.headers(), params=params)
                    if response.status_code in (401, 403):
                        raise_for_status(response, self.host)
                    if response.status_code >= 400:
                        break
                    body = response.json()
                    for item in body.get("models", []):
                        if not isinstance(item, dict):
                            continue
                        methods = item.get("supportedGenerationMethods") or []
                        if methods and "generateContent" not in methods:
                            continue
                        name = str(item.get("name", ""))
                        if name.startswith("models/"):
                            name = name[7:]
                        if name:
                            names.append(name)
                    token = body.get("nextPageToken")
                    if not token or token in seen:
                        break
                    seen.add(token)
                    params["pageToken"] = token
                if names:
                    return sorted(set(names))
        except httpx.HTTPError as exc:
            if not self.static_models:
                raise wrap_transport_error(exc, self.host) from exc
        except (json.JSONDecodeError, ValueError):
            pass
        if self.static_models:
            return list(self.static_models)
        raise ProviderError(f"{self.host} did not return a model list")


def _declaration(spec: dict) -> dict:
    return {"name": spec["name"], "description": spec.get("description", ""),
            "parameters": _clean_schema(spec.get("parameters") or {})}


def _clean_schema(schema: Any) -> Any:
    """Strip keys Gemini rejects."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key not in SCHEMA_KEYS:
            continue
        if key == "properties" and isinstance(value, dict):
            out[key] = {k: _clean_schema(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _clean_schema(value)
        else:
            out[key] = value
    if out.get("type") == "object" and not out.get("properties"):
        out["properties"] = {}
    return out


def _finish(chunk: dict) -> str:
    for candidate in chunk.get("candidates") or []:
        if isinstance(candidate, dict) and candidate.get("finishReason"):
            return str(candidate["finishReason"])
    return ""


def _consume(chunk: dict, calls: list[ToolCall], parts: list[dict] | None = None) -> list:
    events = []
    usage = chunk.get("usageMetadata")
    if isinstance(usage, dict):
        events.append(Usage(int(usage.get("promptTokenCount") or 0),
                            int(usage.get("candidatesTokenCount") or 0)))
    for candidate in chunk.get("candidates") or []:
        if not isinstance(candidate, dict):
            continue
        for part in (candidate.get("content") or {}).get("parts") or []:
            if not isinstance(part, dict):
                continue
            if parts is not None:
                # Preserve boundaries and opaque signatures, including empty text
                # parts sent at the end of a stream. Never merge signed parts.
                parts.append(copy.deepcopy(part))
            if "text" in part and part["text"]:
                text = str(part["text"])
                if part.get("thought"):
                    events.append(ThinkingDelta(text))
                else:
                    events.append(TextDelta(text))
            call = part.get("functionCall")
            if isinstance(call, dict) and call.get("name"):
                args = call.get("args")
                calls.append(ToolCall(f"call_{len(calls)}", str(call["name"]),
                                      args if isinstance(args, dict) else {}))
    return events


def to_gemini_contents(messages: list[dict]) -> list[dict]:
    """Convert internal history to Gemini contents."""
    names: dict[str, str] = {}
    out: list[dict] = []
    for message in provider_history(messages):
        role = message.get("role")
        if role in ("user", "system"):
            parts = [{"text": message.get("content", "")}]
            for item in message.get("attachments") or []:
                parts.append({"inlineData": {"mimeType": item.get("mime_type"),
                                             "data": item.get("data")}})
            _append(out, "user", parts)
        elif role == "assistant":
            for call in message.get("tool_calls") or []:
                names[call["id"]] = call["name"]
            if message.get("gemini_parts"):
                out.append({"role": "model", "parts": copy.deepcopy(message["gemini_parts"])})
                continue
            parts: list[dict] = []
            text = message.get("content") or ""
            if text:
                parts.append({"text": text})
            for call in message.get("tool_calls") or []:
                names[call["id"]] = call["name"]
                parts.append({"functionCall": {"name": call["name"],
                                               "args": call.get("arguments") or {}},
                              "thoughtSignature": CLIENT_CALL_SIGNATURE})
            if parts:
                out.append({"role": "model", "parts": parts})
        elif role == "tool":
            name = message.get("name") or names.get(message.get("tool_call_id", ""), "tool")
            _append(out, "user", [{"functionResponse": {
                "name": name,
                "response": {"output": message.get("content", "") or "(no output)"}}}])
    return out


def _append(out: list[dict], role: str, parts: list[dict]) -> None:
    if out and out[-1]["role"] == role:
        out[-1]["parts"].extend(parts)
    else:
        out.append({"role": role, "parts": parts})
