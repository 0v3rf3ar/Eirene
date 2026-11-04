"""llama-server connections, budgets and wire behavior, against its documented API."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from eirene.commands.connect import run
from eirene.commands.think import run as think
from eirene.core.config import Config
from eirene.core.errors import AuthError, CommandError, ConnectionFailed, ProviderError, error_kind
from eirene.providers import base, registry
from eirene.providers.base import Done, TextDelta, ToolCall, Usage
from eirene.providers.llamacpp import LlamaCpp, context_tier
from eirene.providers.local_profile import LocalProfile

ROOT = "http://localhost:9931"
PATH_ID = "/home/me/models/Qwen3-8B-Q4_K_M.gguf"


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


@pytest.fixture(autouse=True)
def strong_machine(monkeypatch):
    """Tiers below come from the server, not from whatever runs these tests."""
    monkeypatch.setattr(LocalProfile, "detect", classmethod(
        lambda cls, model="": cls("full", None, 64, 16, 24)))


def model_list(n_ctx=65536, ident=PATH_ID, modalities=("text",), **meta):
    entry = {"id": ident, "object": "model", "owned_by": "llamacpp",
             "meta": {"n_ctx": n_ctx, "n_ctx_train": 131072, "n_params": 8_030_261_312, **meta}}
    if modalities is not None:
        entry["architecture"] = {"input_modalities": list(modalities), "output_modalities": ["text"]}
    return {"object": "list", "data": [entry]}


def sse(*chunks):
    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
    return httpx.Response(200, content="".join(lines) + "data: [DONE]\n\n",
                          headers={"content-type": "text/event-stream"})


def server(routes, seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request)
        reply = routes[request.url.path]
        return reply(request) if callable(reply) else reply
    base.set_transport(httpx.MockTransport(handler))


def models_route(**kwargs):
    return httpx.Response(200, json=model_list(**kwargs))


def test_registry_entry_and_names():
    config = Config.load()
    provider = registry.build("llamacpp", config)
    assert isinstance(provider, LlamaCpp)
    assert provider.base_url == f"{ROOT}/v1"
    assert provider.timeout >= 600
    assert "Authorization" not in provider.headers()
    for name in ("llama.cpp", "llama-cpp", "llama_cpp", "llama", "llama-server", "llamacpp"):
        assert registry.resolve_alias(name) == "llamacpp"
    assert registry.display_name("llamacpp", compact=True) == "llama.cpp"


@pytest.mark.parametrize("url", ["http://box:8080", "http://box:8080/", "http://box:8080/v1", "http://box:8080/v1/"])
def test_root_and_api_addresses_are_both_accepted(url):
    provider = LlamaCpp(None, url)
    assert provider.base_url == "http://box:8080/v1"
    assert provider.server_root == "http://box:8080"


def test_proxies_are_skipped_only_for_this_machine():
    assert LlamaCpp(None, ROOT).trust_env is False
    assert LlamaCpp(None, "http://box:8080").trust_env is True


def test_short_server_keys_are_allowed_for_llamacpp_only():
    assert registry.validate_key("llamacpp", "abc") == "abc"
    with pytest.raises(ProviderError):
        registry.validate_key("anthropic", "abc")


async def test_model_path_is_shortened_but_sent_exactly():
    seen = []
    server({"/v1/models": models_route(), "/v1/chat/completions": sse(
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]})}, seen)
    provider = LlamaCpp(None, ROOT)
    assert await provider.models() == ["Qwen3-8B-Q4_K_M.gguf"]
    events = [event async for event in provider.stream(
        [{"role": "user", "content": "hello"}], "Qwen3-8B-Q4_K_M.gguf")]
    assert TextDelta("hi") in events
    body = json.loads(seen[-1].content)
    assert body["model"] == PATH_ID
    assert body["stream_options"] == {"include_usage": True}


async def test_alias_and_router_names_are_kept():
    server({"/v1/models": models_route(ident="ggml-org/gemma-3-4b-it-GGUF:Q4_K_M")})
    assert await LlamaCpp(None, ROOT).models() == ["ggml-org/gemma-3-4b-it-GGUF:Q4_K_M"]


@pytest.mark.parametrize(("context", "tier"), [
    (2048, "compact"), (8191, "compact"), (8192, "balanced"), (32767, "balanced"), (32768, "full")])
def test_tier_follows_the_window(context, tier):
    assert context_tier(context) == tier


async def test_server_context_is_used_as_loaded():
    server({"/v1/models": models_route(n_ctx=65536)})
    provider = LlamaCpp(None, ROOT)
    # The memory is already allocated, so a window above the tier's own allowance is honored.
    assert await provider.prepare_context(PATH_ID) == 65536
    assert provider.profile.tier == "full"


async def test_small_server_context_shrinks_instructions_and_replies():
    server({"/v1/models": models_route(n_ctx=4096)})
    provider = LlamaCpp(None, ROOT)
    assert await provider.prepare_context(PATH_ID) == 4096
    assert provider.profile.tier == "compact"
    assert provider.profile.max_tokens == 1024


async def test_weak_local_machine_limits_a_large_window(monkeypatch):
    monkeypatch.setattr(LocalProfile, "detect", classmethod(
        lambda cls, model="": cls("compact", None, 8, 4, 0)))
    server({"/v1/models": models_route(n_ctx=65536)})
    provider = LlamaCpp(None, ROOT)
    assert await provider.prepare_context(PATH_ID) == 65536
    assert provider.profile.tier == "compact"


async def test_remote_server_ignores_this_machines_hardware(monkeypatch):
    monkeypatch.setattr(LocalProfile, "detect", classmethod(
        lambda cls, model="": cls("compact", None, 8, 4, 0)))
    server({"/v1/models": models_route(n_ctx=65536)})
    provider = LlamaCpp(None, "http://gpu-box:8080")
    await provider.prepare_context(PATH_ID)
    assert provider.profile.tier == "full"


async def test_older_servers_are_read_from_props_without_loading_anything():
    seen = []
    listing = model_list(modalities=None)
    del listing["data"][0]["meta"]["n_ctx"]
    server({"/v1/models": httpx.Response(200, json=listing),
            "/props": httpx.Response(200, json={"default_generation_settings": {"n_ctx": 16384},
                                                "modalities": {"vision": True}})}, seen)
    provider = LlamaCpp(None, ROOT)
    assert await provider.prepare_context(PATH_ID) == 16384
    assert provider.profile.tier == "balanced"
    assert provider.supports_images(PATH_ID) is True
    assert seen[-1].url.params["autoload"] == "false"


async def test_unloaded_router_model_falls_back_to_the_profile():
    listing = {"data": [{"id": "a:Q4", "status": {"value": "unloaded"}}, {"id": "b:Q4"}]}
    server({"/v1/models": httpx.Response(200, json=listing),
            "/props": httpx.Response(400, json={"error": {"message": "model is not loaded"}})})
    provider = LlamaCpp(None, ROOT)
    assert await provider.prepare_context("a:Q4") == provider.profile.context_tokens


async def test_server_restart_is_noticed_after_the_reading_expires(monkeypatch):
    sizes = iter([4096, 65536])
    server({"/v1/models": lambda request: models_route(n_ctx=next(sizes))})
    provider = LlamaCpp(None, ROOT)
    assert await provider.prepare_context(PATH_ID) == 4096
    assert await provider.prepare_context(PATH_ID) == 4096
    monkeypatch.setattr("eirene.providers.llamacpp.INFO_TTL", -1)
    assert await provider.prepare_context(PATH_ID) == 65536
    assert provider.profile.tier == "full"


async def test_tools_stream_with_usage_and_reasoning_replay():
    seen = []
    server({"/v1/models": models_route(), "/v1/chat/completions": sse(
        {"choices": [{"delta": {"reasoning_content": "Look first."}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1", "type": "function",
                                                "function": {"name": "read_file", "arguments": '{"path":'}}]}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": '"a.py"}'}}]},
                      "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 9}})}, seen)
    provider = LlamaCpp(None, ROOT)
    history = [{"role": "user", "content": "go"},
               {"role": "assistant", "content": "", "reasoning_content": "Earlier.",
                "tool_calls": [{"id": "c0", "name": "read_file", "arguments": {"path": "b.py"}}]},
               {"role": "tool", "tool_call_id": "c0", "name": "read_file", "content": "ok"}]
    events = [event async for event in provider.stream(
        history, PATH_ID, system="You are Eirene.",
        tools=[{"name": "read_file", "description": "x", "parameters": {"type": "object"}}])]
    assert ToolCall("c1", "read_file", {"path": "a.py"}) in events
    assert Usage(120, 9) in events
    done = events[-1]
    assert isinstance(done, Done) and done.reason == "tool_use" and done.reasoning_content == "Look first."
    body = json.loads(seen[-1].content)
    assert body["parallel_tool_calls"] is True
    assert body["messages"][2]["reasoning_content"] == "Earlier."
    assert "reasoning_effort" not in body


async def test_no_parallel_flag_without_tools_and_think_off_is_sent():
    seen = []
    server({"/v1/models": models_route(), "/v1/chat/completions": sse(
        {"choices": [{"delta": {"content": "hi"}, "finish_reason": "stop"}]})}, seen)
    provider = LlamaCpp(None, ROOT, think=False)
    [event async for event in provider.stream([{"role": "user", "content": "hello"}], PATH_ID)]
    body = json.loads(seen[-1].content)
    assert "parallel_tool_calls" not in body
    assert body["reasoning_effort"] == "none"


async def test_oversized_request_says_what_to_do():
    overflow = {"error": {"code": 400, "type": "exceed_context_size_error",
                          "message": "request (9000 tokens) exceeds the available context size (8192 tokens), try increasing it"}}
    server({"/v1/models": models_route(n_ctx=8192),
            "/v1/chat/completions": httpx.Response(400, json=overflow)})
    with pytest.raises(ProviderError, match="larger -c value") as caught:
        [event async for event in LlamaCpp(None, ROOT).stream([{"role": "user", "content": "x"}], PATH_ID)]
    assert caught.value.status == 400
    assert "9,000 tokens" in str(caught.value) and "8,192-token" in str(caught.value)
    assert "/compact" in str(caught.value)


async def test_overflow_reported_inside_the_stream_says_what_to_do():
    server({"/v1/models": models_route(n_ctx=8192), "/v1/chat/completions": sse(
        {"error": {"code": 400, "message": "request (9000 tokens) exceeds the available context size (8192 tokens)"}})})
    with pytest.raises(ProviderError, match="larger -c value"):
        [event async for event in LlamaCpp(None, ROOT).stream([{"role": "user", "content": "x"}], PATH_ID)]


async def test_disabled_templates_say_what_to_do():
    server({"/v1/models": models_route(), "/v1/chat/completions": httpx.Response(
        500, json={"error": {"code": 500, "message": "tools param requires --jinja flag"}})})
    with pytest.raises(ProviderError, match="remove that flag") as caught:
        [event async for event in LlamaCpp(None, ROOT).stream([{"role": "user", "content": "x"}], PATH_ID)]
    assert caught.value.retryable is False


async def test_images_are_refused_locally_without_vision():
    seen = []
    server({"/v1/models": models_route(modalities=("text",))}, seen)
    provider = LlamaCpp(None, ROOT)
    message = {"role": "user", "content": "look", "attachments": [{"mime_type": "image/png", "data": "AA"}]}
    with pytest.raises(ProviderError, match="--mmproj"):
        [event async for event in provider.stream([message], PATH_ID)]
    assert all(request.url.path != "/v1/chat/completions" for request in seen)
    assert provider.supports_images(PATH_ID) is False


async def test_images_are_sent_with_vision():
    seen = []
    server({"/v1/models": models_route(modalities=("text", "image")), "/v1/chat/completions": sse(
        {"choices": [{"delta": {"content": "a cat"}, "finish_reason": "stop"}]})}, seen)
    message = {"role": "user", "content": "look", "attachments": [{"mime_type": "image/png", "data": "AA"}]}
    [event async for event in LlamaCpp(None, ROOT).stream([message], PATH_ID)]
    assert json.loads(seen[-1].content)["messages"][0]["content"][1]["type"] == "image_url"


async def test_stopped_server_says_how_to_start_it():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    base.set_transport(httpx.MockTransport(refuse))
    with pytest.raises(ConnectionFailed, match="cannot reach localhost:9931.*llama-server -m"):
        await LlamaCpp(None, ROOT).validate()


async def test_stopped_local_server_fails_at_once_but_remote_ones_retry():
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)
    base.set_transport(httpx.MockTransport(refuse))
    message = [{"role": "user", "content": "x"}]
    with pytest.raises(ConnectionFailed, match="llama-server -m") as caught:
        [event async for event in LlamaCpp(None, ROOT).stream(message, PATH_ID)]
    assert caught.value.retryable is False
    assert error_kind(caught.value) == "network"
    with pytest.raises(ConnectionFailed) as caught:
        [event async for event in LlamaCpp(None, "http://gpu-box:8080").stream(message, PATH_ID)]
    assert caught.value.retryable is True


async def test_loading_server_asks_to_wait():
    loading = httpx.Response(503, json={"error": {"code": 503, "message": "Loading model", "type": "unavailable_error"}})
    server({"/v1/models": loading, "/health": loading})
    with pytest.raises(ProviderError, match="still loading"):
        await LlamaCpp(None, ROOT).validate()


async def test_validate_reports_the_context_and_checks_the_key():
    server({"/v1/models": models_route(n_ctx=65536)})
    assert await LlamaCpp(None, ROOT).validate() == "1 model, 65,536-token context"
    server({"/v1/models": httpx.Response(401, json={"error": {"message": "Invalid API Key"}})})
    with pytest.raises(AuthError):
        await LlamaCpp("wrong", ROOT).validate()


def connect_app(config, *, texts, choices):
    return SimpleNamespace(config=config, say=lambda *args, **kwargs: None,
                           ask_text=AsyncMock(side_effect=texts), ask_choice=AsyncMock(side_effect=choices),
                           _save_config=lambda: None, refresh_mode_line=lambda: None,
                           agent=SimpleNamespace(use=lambda *args: None))


async def test_connect_flow_saves_the_address_and_model():
    server({"/v1/models": models_route()})
    config = Config.load()
    app = connect_app(config, texts=["http://localhost:8080", ""], choices=["Qwen3-8B-Q4_K_M.gguf"])
    await run(app, "llama.cpp")
    assert config.provider == "llamacpp"
    assert config.model == "Qwen3-8B-Q4_K_M.gguf"
    assert config.provider_config("llamacpp")["base_url"] == "http://localhost:8080"
    assert registry.build("llamacpp", config).base_url == "http://localhost:8080/v1"


async def test_think_command_saves_and_rebuilds():
    config = Config.load()
    config.provider = "llamacpp"
    used = []
    app = SimpleNamespace(config=config, say=lambda *args, **kwargs: None, _save_config=lambda: None,
                          agent=SimpleNamespace(model="m", use=lambda provider, key, model: used.append(provider)))
    await think(app, "nothink")
    assert config.provider_config("llamacpp")["think"] is False
    assert used[-1].think is False
    config.provider = "anthropic"
    with pytest.raises(CommandError):
        await think(app, "think")
