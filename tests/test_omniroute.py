"""Manual OmniRoute gateway connections and wire behavior."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from eirene.commands.connect import run
from eirene.core.config import Config
from eirene.core.errors import AuthError, ConnectionFailed, ProviderError
from eirene.providers import base, registry


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def test_optional_key_and_remote_configuration(monkeypatch):
    config = Config.load()
    provider = registry.build("omniroute", config)
    assert provider.base_url == "http://localhost:20128/v1"
    assert "Authorization" not in provider.headers()
    assert registry.default_model("omniroute") == "auto/coding"
    config.set_provider("omniroute", base_url="https://gateway.example/v1")
    monkeypatch.setenv("EIRENE_OMNIROUTE_API_KEY", "gateway-env-token")
    provider = registry.build("omniroute", config)
    assert provider.base_url == "https://gateway.example/v1"
    assert provider.headers()["Authorization"] == "Bearer gateway-env-token"


async def test_live_models_include_combos_and_virtual_routing():
    def handler(request):
        assert str(request.url) == "http://localhost:20128/v1/models"
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"data": [{"id": "my-combo"},
                              {"id": "provider/model"}, {"id": "auto"}]})

    base.set_transport(httpx.MockTransport(handler))
    assert await registry.build("omniroute", Config.load()).models() == [
        "auto/coding", "auto", "my-combo", "provider/model"]


@pytest.mark.parametrize("status,error", [(401, AuthError), (403, AuthError),
                                         (500, ProviderError)])
async def test_connection_check_does_not_hide_gateway_errors(status, error):
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(
        status, json={"error": {"message": "gateway rejected request"}})))
    with pytest.raises(error):
        await registry.build("omniroute", Config.load()).validate()


async def test_stopped_gateway_fails_validation():
    def handler(request):
        raise httpx.ConnectError("connection refused", request=request)

    base.set_transport(httpx.MockTransport(handler))
    with pytest.raises(ConnectionFailed):
        await registry.build("omniroute", Config.load()).validate()


async def test_streaming_tools_usage_and_tool_result_round_trip():
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        assert str(request.url) == "http://localhost:20128/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer gateway-test-token"
        if len(requests) == 1:
            chunks = [
                {"choices": [{"delta": {"reasoning_content": "Inspect files"}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "c1",
                    "function": {"name": "read_file", "arguments": '{"path":'}}]}}]},
                {"choices": [{"delta": {"tool_calls": [{"index": 0,
                    "function": {"arguments": '"README.md"}'}}]},
                    "finish_reason": "tool_calls"}]},
                {"choices": [], "usage": {"prompt_tokens": 42, "completion_tokens": 7}},
            ]
        else:
            chunks = [{"choices": [{"delta": {"content": "Read it"},
                                     "finish_reason": "stop"}]}]
        content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
        return httpx.Response(200, text=content + "data: [DONE]\n\n",
                              headers={"Content-Type": "text/event-stream"})

    base.set_transport(httpx.MockTransport(handler))
    config = Config.load()
    config.set_provider("omniroute", api_key="gateway-test-token")
    provider = registry.build("omniroute", config)
    tools = [{"name": "read_file", "parameters": {"type": "object"}}]
    messages = [{"role": "user", "content": "read README"}]
    events = [e async for e in provider.stream(messages, "auto/coding", tools=tools)]
    call = next(e for e in events if isinstance(e, base.ToolCall))
    assert call.arguments == {"path": "README.md"}
    assert any(isinstance(e, base.ThinkingDelta) for e in events)
    assert base.Usage(42, 7) in events
    assert events[-1] == base.Done("tool_use")
    assert requests[0]["model"] == "auto/coding"
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert requests[0]["tools"][0]["function"]["name"] == "read_file"
    messages += [{"role": "assistant", "tool_calls": [
        {"id": call.id, "name": call.name, "arguments": call.arguments}]},
        {"role": "tool", "tool_call_id": call.id, "content": "# README"}]
    result = [e async for e in provider.stream(messages, "auto/coding", tools=tools)]
    assert base.TextDelta("Read it") in result
    assert requests[1]["messages"][-1] == {
        "role": "tool", "tool_call_id": "c1", "content": "# README"}


@pytest.mark.parametrize("token", ["", "gateway-test-token", None])
async def test_connect_accepts_default_url_optional_key_and_cancellation(token):
    from eirene.core.plugin_install import install
    install("omniroute")
    config = Config.load()
    agent = SimpleNamespace(use=lambda *args: None)
    app = SimpleNamespace(config=config, agent=agent, say=lambda *args: None,
        ask_text=AsyncMock(side_effect=["", token]),
        ask_choice=AsyncMock(return_value="auto/coding"),
        _save_config=lambda: config.save(), refresh_mode_line=lambda: None)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"data": [{"id": "provider/model"}]})

    base.set_transport(httpx.MockTransport(handler))
    await run(app, "omniroute")
    assert app.ask_text.call_args.kwargs == {"secret": True}
    if token is None:
        assert config.provider is None
        assert not requests
    else:
        saved = Config.load()
        assert saved.provider == "omniroute"
        assert saved.model == "auto/coding"
        assert saved.base_url("omniroute") == "http://localhost:20128/v1"
        assert saved.api_key("omniroute") == (token or None)


async def test_connect_remote_gateway_replaces_saved_url_and_key():
    from eirene.core.plugin_install import install
    install("omniroute")
    config = Config.load()
    config.set_provider("omniroute", api_key="old-gateway-key", base_url="https://old/v1")
    app = SimpleNamespace(config=config, agent=SimpleNamespace(use=lambda *args: None),
        say=lambda *args: None, ask_text=AsyncMock(side_effect=["https://new/v1", ""]),
        ask_choice=AsyncMock(return_value="my-combo"), _save_config=lambda: config.save(),
        refresh_mode_line=lambda: None)
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(
        200, json={"data": [{"id": "my-combo"}]})))
    await run(app, "omniroute!")
    assert config.base_url("omniroute") == "https://new/v1"
    assert config.api_key("omniroute") is None
    assert config.model == "my-combo"



async def test_legacy_managed_settings_only_connect_to_existing_gateway(monkeypatch):
    config = Config.load()
    config.set_provider('omniroute',api_key='external-key',base_url='http://127.0.0.1:20128/v1')
    config.provider_config('omniroute')['managed']=True
    config.set('plugin_trust',{'omniroute':True})
    monkeypatch.setattr('asyncio.create_subprocess_exec',
        AsyncMock(side_effect=AssertionError('manual connection must not launch subprocesses')))
    base.set_transport(httpx.MockTransport(lambda request: httpx.Response(
        200,json={'data':[{'id':'provider/model'}]})))
    provider=registry.build('omniroute',config)
    assert await provider.models()==['auto/coding','auto','provider/model']
    assert not hasattr(provider,'managed')
