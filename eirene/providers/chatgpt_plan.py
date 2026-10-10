"""Responses inference using an authorized ChatGPT plan; Eirene runs tools."""

from __future__ import annotations

import json

import httpx

from ..core.errors import AuthError, ProviderError
from .base import (Done, Provider, TextDelta, ThinkingDelta, ToolCall, Usage,
                   parse_json, raise_for_status, sse_lines, transient_tls_error,
                   wrap_transport_error)
from .chatgpt_auth import ChatGPTAuth, RESOURCE


class ChatGPTPlan(Provider):
    name = "chatgpt-plan"
    protocol = "chatgpt-responses"

    def __init__(self, *, timeout=300.0, reasoning_efforts=None):
        super().__init__(None, RESOURCE, timeout=timeout)
        self.auth = ChatGPTAuth(timeout=timeout)
        self.reasoning_efforts = dict(reasoning_efforts or {})
        self._catalog = {}

    async def _headers(self):
        return {"Content-Type": "application/json",
                "Authorization": "Bearer " + await self.auth.access_token()}

    def _status(self, response, model=""):
        if response.status_code in (401, 403):
            raise AuthError("ChatGPT plan access was rejected; reconnect with /connect chatgpt-plan")
        raise_for_status(response, "ChatGPT", model)

    async def models(self):
        try:
            async with self._client() as client:
                response = await client.get(self.base_url + "/models", headers=await self._headers())
                self._status(response)
                body = response.json()
                self._catalog = {item["slug"]: item for item in body.get("models", [])
                                 if isinstance(item, dict) and item.get("slug")}
                names = [str(item["slug"]) for item in body.get("models", [])
                         if isinstance(item, dict) and item.get("visibility") == "list" and item.get("slug")]
                if not names:
                    raise ProviderError("no models available for this ChatGPT account")
                return list(dict.fromkeys(names))
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, "ChatGPT") from exc
        except (ValueError, AttributeError) as exc:
            raise ProviderError("ChatGPT returned an invalid model catalog") from exc

    async def reasoning_options(self, model):
        if model not in self._catalog:
            await self.models()
        metadata = self._catalog.get(model, {})
        default = metadata.get("default_reasoning_level")
        options = [("default", "model default", f"currently {default}" if default else "use the model's default")]
        for level in metadata.get("supported_reasoning_levels") or []:
            effort = level.get("effort") if isinstance(level, dict) else level
            if effort in {"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"}:
                description = level.get("description", "") if isinstance(level, dict) else ""
                options.append((effort, effort, description))
        return options

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        for attempt in range(2):
            progressed = False
            try:
                async for event in self._stream_once(messages, model, system=system,
                                                     tools=tools, max_tokens=max_tokens):
                    if isinstance(event, (TextDelta, ToolCall)):
                        progressed = True
                    yield event
                return
            except ProviderError as exc:
                detail = str(exc.__cause__ or exc)
                if attempt or progressed or not transient_tls_error(detail):
                    raise

    async def _stream_once(self, messages, model, *, system="", tools=None, max_tokens=8192):
        body = {"model": model, "input": to_responses_input(messages),
                "store": False, "stream": True, "include": ["reasoning.encrypted_content"]}
        if system:
            body["instructions"] = system
        effort = self.reasoning_efforts.get(model, "default")
        if effort != "default":
            body["reasoning"] = {"effort": effort}
        allowed_names = {spec["name"] for spec in tools or []}
        if tools:
            body["tools"] = [{"type": "namespace", "name": "eirene",
                              "description": "Eirene workspace tools",
                              "tools": [{"type": "function", **spec, "strict": False} for spec in tools]}]
        completed = None
        items = {}
        text_parts = {}

        def remaining_text(index, content_index, text):
            key = (index, content_index)
            seen = text_parts.get(key, "")
            if not seen:
                text_parts[key] = text
                return text
            if text.startswith(seen):
                text_parts[key] = text
                return text[len(seen):]
            return ""

        def item_text(index, item):
            if item.get("type") != "message":
                return []
            result = []
            for content_index, part in enumerate(item.get("content") or []):
                if part.get("type") in {"output_text", "refusal"}:
                    delta = remaining_text(index, content_index, part.get("text") or part.get("refusal") or "")
                    if delta:
                        result.append(TextDelta(delta))
            return result
        try:
            async with self._client() as client:
                async with client.stream("POST", self.base_url + "/responses", json=body,
                                         headers=await self._headers()) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        self._status(response, model)
                    async for event_name, data in sse_lines(response):
                        event = parse_json(data)
                        if not isinstance(event, dict):
                            continue
                        kind = event.get("type") or event_name
                        index = event.get("output_index", 0)
                        content_index = event.get("content_index", 0)
                        if kind in {"response.output_text.delta", "response.refusal.delta"}:
                            delta = str(event.get("delta", ""))
                            part_key = (index, content_index)
                            text_parts[part_key] = text_parts.get(part_key, "") + delta
                            if delta:
                                yield TextDelta(delta)
                        elif kind in {"response.output_text.done", "response.refusal.done"}:
                            delta = remaining_text(index, content_index,
                                event.get("text") or event.get("refusal") or "")
                            if delta:
                                yield TextDelta(delta)
                        elif kind == "response.output_item.done":
                            item = event.get("item")
                            if isinstance(item, dict):
                                items[index] = item
                                for text_event in item_text(index, item):
                                    yield text_event
                        elif kind in {"response.reasoning_summary_text.delta", "response.reasoning_text.delta"}:
                            yield ThinkingDelta(str(event.get("delta", "")))
                        elif kind == "response.completed":
                            completed = event.get("response", {})
                            break
                        elif kind in {"error", "response.failed", "response.incomplete"}:
                            # Do not treat a partial tool call as executable.
                            raise ProviderError("ChatGPT did not complete the response; try again or check your plan usage")
        except httpx.HTTPError as exc:
            raise wrap_transport_error(exc, "ChatGPT") from exc
        if not isinstance(completed, dict) or completed.get("status") != "completed":
            raise ProviderError("ChatGPT response stream ended before completion")
        output = completed.get("output") or []
        if not isinstance(output, list):
            raise ProviderError("ChatGPT returned invalid response output")
        # Plan streams can omit output from response.completed. Completed item
        # events contain the actual messages, calls, and encrypted reasoning.
        for index, item in enumerate(output):
            if isinstance(item, dict):
                items.setdefault(index, item)
        output = [items[index] for index in sorted(items)]
        for index in sorted(items):
            for text_event in item_text(index, items[index]):
                yield text_event
        if not any(item.get("type") == "message" for item in output) and text_parts:
            output.append({"type": "message", "role": "assistant", "content": [
                {"type": "output_text", "text": text_parts[key], "annotations": []}
                for key in sorted(text_parts)]})
        calls = []
        for item in output:
            if not isinstance(item, dict) or item.get("type") != "function_call":
                continue
            name = str(item.get("name", ""))
            namespace = item.get("namespace")
            if name.startswith("eirene."):
                name = name[len("eirene."):]
            if namespace not in (None, "", "eirene") or name not in allowed_names:
                raise ProviderError("ChatGPT requested an unknown workspace tool")
            try:
                arguments = json.loads(item.get("arguments", ""))
                if not isinstance(arguments, dict) or not item.get("call_id"):
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ProviderError("ChatGPT returned invalid tool arguments") from exc
            calls.append(ToolCall(item["call_id"], name, arguments))
        if not calls and not any(text_parts.values()):
            raise ProviderError("ChatGPT returned no answer or tool calls; try again or choose another model with /model")
        usage = completed.get("usage") or {}
        yield Usage(int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
        for call in calls:
            yield call
        yield Done("tool_use" if calls else "stop", response_items=output)

    async def close(self):
        await self.auth.close()


def to_responses_input(messages):
    """Replay local history, including encrypted reasoning and tool results."""
    result = []
    for message in messages:
        role = message.get("role")
        if role == "assistant" and message.get("response_items"):
            result.extend(message["response_items"])
            continue
        if role == "tool":
            result.append({"type": "function_call_output", "call_id": message.get("tool_call_id", ""),
                           "output": message.get("content") or ""})
        elif role in {"user", "system", "developer", "assistant"}:
            text = message.get("content") or ""
            content = [{"type": "output_text" if role == "assistant" else "input_text", "text": text}]
            if role == "user":
                content.extend({"type": "input_image", "image_url":
                    f"data:{item.get('mime_type')};base64,{item.get('data')}"}
                    for item in message.get("attachments") or [])
            if text or len(content) > 1:
                result.append({"type": "message", "role": "developer" if role == "system" else role,
                               "content": content})
            for call in message.get("tool_calls") or []:
                result.append({"type": "function_call", "call_id": call["id"],
                               "name": call["name"], "namespace": "eirene",
                               "arguments": json.dumps(call.get("arguments") or {})})
    return result
