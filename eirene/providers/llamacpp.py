"""llama.cpp's llama-server: OpenAI's protocol, with Eirene's local-model budgets.

Unlike Ollama, the server fixes its context size when it starts, so Eirene reads
that size instead of asking for one, and an oversized request is an error rather
than a silent truncation. The server also picks its own model unless it runs in
router mode, where the model field selects one and loads it on demand.
"""

from __future__ import annotations

import dataclasses
import json
import posixpath
import re
import time
from typing import Any, AsyncIterator
from urllib.parse import urlparse

import httpx

from ..core.errors import AuthError, ConnectionFailed, ProviderError
from .local_profile import LocalProfile
from .openai_compat import OpenAICompatible

# How long a reading of the server is reused: it can restart with other settings.
INFO_TTL = 30.0
TIERS = ("compact", "balanced", "full")
LOOPBACK = {"localhost", "127.0.0.1", "::1"}
START_ADVICE = ("start it with: llama-server -m /path/to/model.gguf, then use the address it "
                "prints; the default port differs between llama.cpp versions")
_OVERFLOW = re.compile(r"\((\d+) tokens\) exceeds the available context size \((\d+) tokens\)")


@dataclasses.dataclass
class ServerInfo:
    context: int = 0
    trained_context: int = 0
    parameters: int = 0
    vision: bool | None = None


def context_tier(context: int) -> str:
    """The largest profile whose instructions and tools fit this window."""
    if context < 8192:
        return "compact"
    return "balanced" if context < 32768 else "full"


class LlamaCpp(OpenAICompatible):
    """A running llama-server, local or on another machine."""

    def __init__(self, api_key, base_url, *, timeout=600.0, think: bool = True):
        url = base_url.rstrip("/")
        parsed = urlparse(url)
        # The server prints its root address; accept that as well as the API root.
        if parsed.path in {"", "/"}:
            url += "/v1"
        super().__init__(api_key, url, name="llamacpp", timeout=timeout)
        self.is_local = parsed.hostname in LOOPBACK
        # A proxy in the environment cannot reach this machine's own server.
        self.trust_env = not self.is_local
        self.think = think
        self.profile = LocalProfile.detect()
        self._info: dict[str, tuple[float, ServerInfo]] = {}
        self._wire_names: dict[str, str] = {}

    @property
    def server_root(self) -> str:
        return self.base_url.removesuffix("/v1")

    async def models(self) -> list[str]:
        try:
            names = await super().models()
        except ConnectionFailed as exc:
            raise ConnectionFailed(self.host, START_ADVICE) from exc
        except AuthError:
            raise
        except ProviderError as exc:
            if await self._loading():
                raise ProviderError(f"llama-server at {self.host} is still loading its model; try again shortly",
                                    retryable=True) from exc
            raise
        shown = []
        catalog = {}
        for name in names:
            # The id is the file's full path unless the server was given --alias.
            short = posixpath.basename(name.replace("\\", "/")) if name.lower().endswith(".gguf") else name
            shown.append(short)
            self._wire_names[short] = name
            catalog[short] = self._catalog.get(name, {})
        self._catalog = catalog
        return shown

    async def validate(self, model: str = "") -> str:
        names = await self.models()
        info = await self._read_info(model or names[0]) if names else ServerInfo()
        count = f"{len(names)} model{'' if len(names) == 1 else 's'}"
        return f"{count}, {info.context:,}-token context" if info.context else count

    async def prepare_context(self, model: str) -> int:
        """Choose the profile from what the running server really has."""
        info = await self._read_info(model)
        details = {"parameter_size": f"{info.parameters / 1e9:.2f}B"} if info.parameters else None
        profile = self.profile.with_model(model, details)
        # Another machine's hardware says nothing about this one's.
        ceiling = profile.tier if self.is_local else "full"
        if info.context:
            ceiling = min(ceiling, context_tier(info.context), key=TIERS.index)
        self.profile = dataclasses.replace(profile, tier=ceiling)
        if info.context:
            return info.context
        fallback = self.profile.context_tokens
        return min(fallback, info.trained_context) if info.trained_context else fallback

    def supports_images(self, model: str) -> bool | None:
        cached = self._info.get(model)
        return cached[1].vision if cached else None

    async def stream(self, messages, model, *, system="", tools=None,
                     max_tokens=8192) -> AsyncIterator:
        await self.prepare_context(model)
        if tools is not None:
            system = self.profile.system(system)
        tools = self.profile.tools(tools)
        max_tokens = min(max_tokens, self.profile.max_tokens)
        if self.supports_images(model) is False and any(m.get("attachments") for m in messages):
            raise ProviderError(f"{model} was not started with vision support; "
                                "add --mmproj to llama-server or use a model that reads images")
        try:
            async for event in super().stream(messages, model, system=system, tools=tools,
                                              max_tokens=max_tokens):
                yield event
        except ConnectionFailed as exc:
            if not self.is_local:
                raise
            # Backing off for minutes cannot start a stopped server on this machine.
            stopped = ConnectionFailed(self.host, START_ADVICE)
            stopped.retryable = False
            raise stopped from exc
        except ProviderError as exc:
            hint = self._explain(str(exc))
            if not hint:
                raise
            raise ProviderError(hint, status=exc.status) from exc

    def _body(self, messages, model, system, tools, max_tokens) -> dict[str, Any]:
        payload = super()._body(messages, model, system, tools, max_tokens)
        payload["model"] = self._wire_names.get(model, model)
        payload["stream_options"] = {"include_usage": True}
        if payload.get("tools"):
            # Off by default on the server; the agent can run a batch of calls.
            payload["parallel_tool_calls"] = True
        if not self.think:
            payload["reasoning_effort"] = "none"
        return payload

    def _explain(self, detail: str) -> str:
        """Replace generic advice where this server's own fix is known."""
        sizes = _OVERFLOW.search(detail)
        if sizes:
            return (f"this request ({int(sizes[1]):,} tokens) is larger than llama-server's "
                    f"{int(sizes[2]):,}-token context. Run /compact, or restart the server with a larger -c value.")
        # base.explain has already replaced the server's wording for any template error.
        if "chat template rejected" in detail:
            return f"{detail} If llama-server was started with --no-jinja, remove that flag: tools need it."
        return ""

    async def _loading(self) -> bool:
        try:
            async with self._client() as client:
                response = await client.get(f"{self.server_root}/health", timeout=5)
            return response.status_code == 503
        except httpx.HTTPError:
            return False

    async def _read_info(self, model: str) -> ServerInfo:
        cached = self._info.get(model)
        if cached and time.monotonic() - cached[0] < INFO_TTL:
            return cached[1]
        info = await self._probe(model)
        if info is None:
            # The request that follows reports an unreachable server by itself.
            return cached[1] if cached else ServerInfo()
        self._info[model] = (time.monotonic(), info)
        return info

    async def _probe(self, model: str) -> ServerInfo | None:
        wire = self._wire_names.get(model, model)
        try:
            async with self._client() as client:
                response = await client.get(f"{self.base_url}/models", headers=self.headers(), timeout=10)
                if response.status_code >= 400:
                    return None
                listed = _model_entry(response.json(), wire)
                info = _info_from_model(listed)
                if info.context and info.vision is not None:
                    return info
                # Older builds report these only here. autoload=false: looking at a
                # router's model must not load it into memory.
                response = await client.get(f"{self.server_root}/props", headers=self.headers(), timeout=10,
                                            params={"model": wire, "autoload": "false"})
                if response.status_code < 400:
                    _add_props(info, response.json())
                return info
        except (httpx.HTTPError, json.JSONDecodeError, ValueError):
            return None


def _model_entry(body: Any, wire: str) -> dict:
    items = body.get("data") if isinstance(body, dict) else None
    items = [item for item in items or [] if isinstance(item, dict)]
    # A single-model server answers for its one model under any name.
    named = next((item for item in items if item.get("id") == wire), None)
    return named or (items[0] if len(items) == 1 else {})


def _positive(value: Any) -> int:
    return value if isinstance(value, int) and value > 0 else 0


def _info_from_model(entry: dict) -> ServerInfo:
    meta = entry.get("meta")
    meta = meta if isinstance(meta, dict) else {}
    info = ServerInfo(_positive(meta.get("n_ctx")), _positive(meta.get("n_ctx_train")),
                      _positive(meta.get("n_params")))
    architecture = entry.get("architecture")
    inputs = architecture.get("input_modalities") if isinstance(architecture, dict) else None
    if isinstance(inputs, list):
        info.vision = "image" in inputs
    return info


def _add_props(info: ServerInfo, body: Any) -> None:
    if not isinstance(body, dict):
        return
    settings = body.get("default_generation_settings")
    if not info.context and isinstance(settings, dict):
        info.context = _positive(settings.get("n_ctx"))
    modalities = body.get("modalities")
    if info.vision is None and isinstance(modalities, dict) and isinstance(modalities.get("vision"), bool):
        info.vision = modalities["vision"]
