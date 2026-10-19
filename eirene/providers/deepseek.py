"""DeepSeek Chat Completions, with model capabilities and thinking controls."""
from __future__ import annotations

import base64
import binascii
import hashlib
import io
import json
import re

from ..core.errors import AuthError, ProviderError
from .base import ToolCall
from .openai_compat import OpenAICompatible

MODELS = ["deepseek-flash", "deepseek-v4-pro"]
CONTEXT_WINDOW = 1_048_576
MAX_OUTPUT_TOKENS = 393_216
MAX_REQUEST_BYTES = 48 * 1024 * 1024
FLASH_ALIASES = {"deepseek-flash", "deepseek-v4-flash", "deepseek-v4-flash-vision-exp"}


class DeepSeek(OpenAICompatible):
    require_finish_reason = True

    def __init__(self, api_key, base_url="https://api.deepseek.com/v1", *,
                 name="deepseek", timeout=300.0, reasoning_efforts=None):
        super().__init__(api_key, base_url, name=name, static_models=MODELS, timeout=timeout)
        self.reasoning_efforts = dict(reasoning_efforts or {})
        self._context_checked: set[str] = set()

    def _positive_limit(self, model, key, fallback):
        value = self._catalog.get(model, {}).get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else fallback

    def context_window(self, model):
        fallback = CONTEXT_WINDOW if model in {*MODELS, *FLASH_ALIASES} else 0
        return self._positive_limit(model, "context_window", fallback)

    def output_limit(self, model):
        return self._positive_limit(model, "max_output_tokens", MAX_OUTPUT_TOKENS)

    async def resolve_context_window(self, model):
        if model not in self._catalog and model not in self._context_checked:
            try:
                await self.models()
            except AuthError:
                raise
            except ProviderError:
                # Model discovery may be unavailable while inference still works.
                pass
            self._context_checked.add(model)
        return self.context_window(model)

    def supports_images(self, model):
        modalities = self._catalog.get(model, {}).get("input_modalities")
        if isinstance(modalities, list):
            return "image" in modalities
        if model in FLASH_ALIASES:
            return True
        if model in {"deepseek-v4-pro", "deepseek-chat", "deepseek-reasoner"}:
            return False
        return None  # An unfamiliar model needs live metadata to decide.

    async def reasoning_options(self, model):
        await self.resolve_context_window(model)
        effort = self._catalog.get(model, {}).get("effort") or {}
        levels = effort.get("supported_levels", ["low", "high", "max"])
        options = [("default", "model default", "use the server's thinking default"),
                   ("none", "off", "answer without thinking mode")]
        options.extend((level, level, "thinking effort") for level in levels
                       if level in {"low", "high", "max"})
        return options

    def _body(self, messages, model, system, tools, max_tokens):
        body = super()._body(messages, model, system, tools, max_tokens)
        if body.get("tools"):
            body["tools"] = [{"type": "function", "function": {
                **tool["function"], "name": _tool_name(tool["function"]["name"])}}
                for tool in body["tools"]]
        # Also applies when this adapter is selected through a custom endpoint.
        for entry in body["messages"]:
            if entry["role"] == "assistant":
                entry["reasoning_content"] = entry.get("reasoning_content") or ""
                for call in entry.get("tool_calls") or []:
                    call["function"]["name"] = _tool_name(call["function"]["name"])
        effort = self.reasoning_efforts.get(model, "default")
        if effort not in {"default", "none", "low", "high", "max"}:
            raise ProviderError(f"unsupported DeepSeek reasoning effort {effort!r}; select it again with /model")
        supported = (self._catalog.get(model, {}).get("effort") or {}).get("supported_levels")
        if isinstance(supported, list) and effort not in {"default", "none"} and effort not in supported:
            raise ProviderError(f"{model} no longer supports {effort!r} thinking effort; select it again with /model")
        if effort != "default":
            body["thinking"] = {"type": "disabled" if effort == "none" else "enabled"}
            if effort != "none":
                body["reasoning_effort"] = effort
        body["max_tokens"] = max(1, min(max_tokens, self.output_limit(model)))
        body["stream_options"] = {"include_usage": True}
        self._validate_payload(body, model)
        return body

    async def stream(self, messages, model, *, system="", tools=None, max_tokens=8192):
        names = {spec["name"] for spec in tools or []}
        names.update(call["name"] for m in messages for call in m.get("tool_calls") or [])
        aliases = {_tool_name(name): name for name in names}
        if len(aliases) != len(names):
            raise ProviderError("DeepSeek tool name aliases conflict; rename the conflicting MCP tools")
        stream = super().stream(messages, model, system=system, tools=tools, max_tokens=max_tokens)
        try:
            async for event in stream:
                if isinstance(event, ToolCall):
                    event.name = aliases.get(event.name, event.name)
                yield event
        finally:
            await stream.aclose()

    def _validate_payload(self, body, model):
        names = [tool["function"]["name"] for tool in body.get("tools", [])]
        if len(names) != len(set(names)) or any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name) for name in names):
            raise ProviderError("DeepSeek requires unique tool names containing 1–128 letters, digits, underscores or dashes; check MCP tool names")
        images = [part for message in body["messages"]
                  if isinstance(message.get("content"), list)
                  for part in message["content"] if part.get("type") == "image_url"]
        if images and self.supports_images(model) is False:
            raise ProviderError(f"{model} does not accept images; select deepseek-flash with /model")
        if len(images) > 600:
            raise ProviderError("DeepSeek accepts at most 600 images per request; start a new session or compact the history")
        if len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ProviderError("DeepSeek request exceeds 48 MiB; use smaller images, compact the history, or start a new session")
        if images:
            from PIL import Image, UnidentifiedImageError
            dimension_limit = 4096 if len(images) >= 15 else 8192
            for part in images:
                url = part["image_url"]["url"]
                if not url.startswith("data:"):
                    continue
                try:
                    data = base64.b64decode(url.split(",", 1)[1], validate=True)
                    if len(data) > 32 * 1024 * 1024:
                        raise ProviderError("DeepSeek inline images must be at most 32 MiB; resize the image")
                    with Image.open(io.BytesIO(data)) as image:
                        if image.format not in {"JPEG", "PNG", "GIF", "WEBP"}:
                            raise ProviderError("DeepSeek requires JPEG, PNG, GIF or WebP images")
                        if max(image.size) > dimension_limit:
                            raise ProviderError(f"DeepSeek image dimensions exceed {dimension_limit} pixels per side; resize the image")
                except (IndexError, ValueError, binascii.Error, OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                    raise ProviderError("DeepSeek image is invalid; attach a valid JPEG, PNG, GIF or WebP image") from exc

    async def isolated_stream(self, messages, model, **kwargs):
        # Titles, summaries, choices and suggestions need their small output
        # budget for text rather than a hidden reasoning-only response.
        clone = DeepSeek(self.api_key, self.base_url, name=self.name, timeout=self.timeout,
                         reasoning_efforts={model: "none"})
        clone._catalog = self._catalog
        try:
            async for event in clone.stream(messages, model, **kwargs):
                yield event
        finally:
            await clone.close()


def _tool_name(name):
    """Keep arbitrary MCP names usable within DeepSeek's wire name limit."""
    if re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", name):
        return name
    prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", name)[:90] or "tool"
    return prefix + "_" + hashlib.sha256(name.encode()).hexdigest()[:32]
