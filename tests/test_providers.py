"""Provider wire protocols, over a mock transport."""

from __future__ import annotations

import json

import httpx
import pytest

from eirene.core.config import Config
from eirene.core.errors import (AuthError, ConnectionFailed, ModelNotFound,
                                ProviderError, RateLimitError)
from eirene.core.session import Message
from eirene.providers import base, registry
from eirene.providers.anthropic_compat import AnthropicCompatible, to_anthropic_messages
from eirene.providers.gemini import Gemini, to_gemini_contents
from eirene.providers.ollama import Ollama, to_ollama_messages
from eirene.providers.openai_compat import OpenAICompatible, to_openai_messages

TOOLS = [{"name": "run_command", "description": "run",
          "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                         "required": ["command"]}}]

HISTORY = [
    Message.user("list the files"),
    Message.assistant("", [{"id": "c1", "name": "run_command",
                            "arguments": {"command": "ls"}}]),
    Message.tool("c1", "run_command", "a.txt\nb.txt"),
    Message.user("thanks"),
]


class Recorder:
    """Captures the request and replays a canned body."""

    def __init__(self, body: str, status: int = 200,
                 headers: dict | None = None, stream: bool = True):
        self.body = body
        self.status = status
        self.headers = headers or {}
        self.stream = stream
        self.request: httpx.Request | None = None

    def transport(self) -> httpx.MockTransport:
        def handler(request: httpx.Request) -> httpx.Response:
            self.request = request
            head = dict(self.headers)
            if self.stream:
                head.setdefault("content-type", "text/event-stream")
            return httpx.Response(self.status, content=self.body.encode(), headers=head)
        return httpx.MockTransport(handler)

    @property
    def payload(self) -> dict:
        assert self.request is not None
        return json.loads(self.request.content)


@pytest.fixture(autouse=True)
def reset_transport():
    yield
    base.set_transport(None)


def install(recorder: Recorder) -> Recorder:
    base.set_transport(recorder.transport())
    return recorder


async def collect(provider, **kwargs) -> list:
    return [event async for event in provider.stream(HISTORY, "m", **kwargs)]


def sse(*chunks: dict | str) -> str:
    lines = []
    for chunk in chunks:
        data = chunk if isinstance(chunk, str) else json.dumps(chunk)
        lines.append(f"data: {data}\n")
    return "\n".join(lines) + "\n"


# openai

OPENAI_STREAM = sse(
    {"choices": [{"delta": {"content": "Hel"}}]},
    {"choices": [{"delta": {"content": "lo"}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "id": "call_1", "function": {"name": "run_command",
                                                  "arguments": '{"comm'}}]}}]},
    {"choices": [{"delta": {"tool_calls": [
        {"index": 0, "function": {"arguments": 'and": "ls"}'}}]}, }]},
    {"choices": [{"delta": {}, "finish_reason": "tool_calls"}],
     "usage": {"prompt_tokens": 12, "completion_tokens": 5}},
    "[DONE]")


async def test_openai_stream_parses():
    install(Recorder(OPENAI_STREAM))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    events = await collect(provider, system="be terse", tools=TOOLS)
    text = "".join(e.text for e in events if isinstance(e, base.TextDelta))
    calls = [e for e in events if isinstance(e, base.ToolCall)]
    usage = [e for e in events if isinstance(e, base.Usage)][-1]
    assert text == "Hello"
    assert calls[0].name == "run_command"
    assert calls[0].arguments == {"command": "ls"}
    assert (usage.input_tokens, usage.output_tokens) == (12, 5)
    assert isinstance(events[-1], base.Done)


async def test_openai_request_shape():
    recorder = install(Recorder(OPENAI_STREAM))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    await collect(provider, system="be terse", tools=TOOLS)
    body = recorder.payload
    assert body["stream"] is True
    assert body["messages"][0] == {"role": "system", "content": "be terse"}
    assert body["tools"][0]["function"]["name"] == "run_command"
    assert recorder.request.headers["authorization"] == "Bearer sk-x"
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]


async def test_openai_reasoning_delta():
    install(Recorder(sse({"choices": [{"delta": {"reasoning_content": "hmm"}}]},
                         "[DONE]")))
    provider = OpenAICompatible("sk-x", "https://api.deepseek.com/v1")
    events = await collect(provider)
    assert any(isinstance(e, base.ThinkingDelta) and e.text == "hmm" for e in events)


async def test_openai_tools_omitted_when_unsupported():
    recorder = install(Recorder(OPENAI_STREAM))
    provider = OpenAICompatible("k", "https://api.perplexity.ai", supports_tools=False)
    await collect(provider, tools=TOOLS)
    assert "tools" not in recorder.payload


async def test_openai_models_list():
    install(Recorder(json.dumps({"data": [{"id": "gpt-4o"}, {"id": "gpt-5"}]}),
                     headers={"content-type": "application/json"}, stream=False))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    assert await provider.models() == ["gpt-4o", "gpt-5"]


async def test_openai_models_fall_back_to_static():
    install(Recorder("nope", status=404, stream=False))
    provider = OpenAICompatible("sk-x", "https://x/v1", static_models=["a", "b"])
    assert await provider.models() == ["a", "b"]


# anthropic

ANTHROPIC_STREAM = "".join([
    "event: message_start\n",
    'data: {"type":"message_start","message":{"usage":{"input_tokens":30,'
    '"output_tokens":0}}}\n\n',
    "event: content_block_start\n",
    'data: {"type":"content_block_start","index":0,'
    '"content_block":{"type":"text","text":""}}\n\n',
    "event: content_block_delta\n",
    'data: {"type":"content_block_delta","index":0,'
    '"delta":{"type":"text_delta","text":"Sure"}}\n\n',
    "event: content_block_start\n",
    'data: {"type":"content_block_start","index":1,'
    '"content_block":{"type":"tool_use","id":"tu_1","name":"run_command"}}\n\n',
    "event: content_block_delta\n",
    'data: {"type":"content_block_delta","index":1,'
    '"delta":{"type":"input_json_delta","partial_json":"{\\"command\\":"}}\n\n',
    "event: content_block_delta\n",
    'data: {"type":"content_block_delta","index":1,'
    '"delta":{"type":"input_json_delta","partial_json":"\\"ls\\"}"}}\n\n',
    "event: message_delta\n",
    'data: {"type":"message_delta","delta":{"stop_reason":"tool_use"},'
    '"usage":{"output_tokens":9}}\n\n',
    "event: message_stop\n",
    'data: {"type":"message_stop"}\n\n',
])


async def test_anthropic_stream_parses():
    install(Recorder(ANTHROPIC_STREAM))
    provider = AnthropicCompatible("sk-ant-x", "https://api.anthropic.com/v1")
    events = await collect(provider, system="be terse", tools=TOOLS)
    text = "".join(e.text for e in events if isinstance(e, base.TextDelta))
    calls = [e for e in events if isinstance(e, base.ToolCall)]
    assert text == "Sure"
    assert calls[0].id == "tu_1"
    assert calls[0].arguments == {"command": "ls"}
    assert events[-1].reason == "tool_use"


async def test_anthropic_request_shape():
    recorder = install(Recorder(ANTHROPIC_STREAM))
    provider = AnthropicCompatible("sk-ant-x", "https://api.anthropic.com/v1")
    await collect(provider, system="be terse", tools=TOOLS)
    body = recorder.payload
    assert body["system"] == "be terse"
    assert body["tools"][0]["input_schema"]["type"] == "object"
    assert recorder.request.headers["x-api-key"] == "sk-ant-x"
    assert recorder.request.headers["anthropic-version"]
    assert [m["role"] for m in body["messages"]] == ["user", "assistant", "user"]


def test_anthropic_merges_tool_results():
    converted = to_anthropic_messages(HISTORY)
    last = converted[-1]
    assert last["role"] == "user"
    kinds = [block["type"] for block in last["content"]]
    assert kinds == ["tool_result", "text"]


def test_anthropic_tool_use_block():
    converted = to_anthropic_messages(HISTORY)
    assert converted[1]["content"][0]["type"] == "tool_use"
    assert converted[1]["content"][0]["input"] == {"command": "ls"}


# gemini

GEMINI_STREAM = sse(
    {"candidates": [{"content": {"parts": [{"text": "Okay"}]}}]},
    {"candidates": [{"content": {"parts": [
        {"functionCall": {"name": "run_command", "args": {"command": "ls"}}}]},
        "finishReason": "STOP"}],
     "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3}})


async def test_gemini_stream_parses():
    install(Recorder(GEMINI_STREAM))
    provider = Gemini("key")
    events = await collect(provider, system="be terse", tools=TOOLS)
    text = "".join(e.text for e in events if isinstance(e, base.TextDelta))
    calls = [e for e in events if isinstance(e, base.ToolCall)]
    assert text == "Okay"
    assert calls[0].arguments == {"command": "ls"}


async def test_gemini_request_shape():
    recorder = install(Recorder(GEMINI_STREAM))
    provider = Gemini("key")
    await collect(provider, system="be terse", tools=TOOLS)
    body = recorder.payload
    assert body["systemInstruction"]["parts"][0]["text"] == "be terse"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "run_command"
    assert recorder.request.headers["x-goog-api-key"] == "key"
    assert "alt=sse" in str(recorder.request.url)


def test_gemini_roles_and_function_response():
    contents = to_gemini_contents(HISTORY)
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert "functionResponse" in contents[2]["parts"][0]


def test_gemini_schema_is_cleaned():
    from eirene.providers.gemini import _clean_schema
    cleaned = _clean_schema({"type": "object", "additionalProperties": False,
                             "$schema": "x", "properties": {"a": {"type": "string"}}})
    assert cleaned == {"type": "object", "properties": {"a": {"type": "string"}}}


# ollama

OLLAMA_STREAM = "\n".join([
    json.dumps({"message": {"content": "Hi"}, "done": False}),
    json.dumps({"message": {"content": "!", "tool_calls": [
        {"function": {"name": "run_command", "arguments": {"command": "ls"}}}]},
        "done": False}),
    json.dumps({"done": True, "prompt_eval_count": 4, "eval_count": 2}),
]) + "\n"


async def test_ollama_stream_parses():
    recorder = install(Recorder(OLLAMA_STREAM,
                                headers={"content-type": "application/x-ndjson"},
                                stream=False))
    provider = Ollama(None, "http://localhost:11434", think=False)
    events = await collect(provider, tools=TOOLS)
    text = "".join(e.text for e in events if isinstance(e, base.TextDelta))
    calls = [e for e in events if isinstance(e, base.ToolCall)]
    usage = [e for e in events if isinstance(e, base.Usage)][-1]
    assert text == "Hi!"
    assert calls[0].arguments == {"command": "ls"}
    assert (usage.input_tokens, usage.output_tokens) == (4, 2)
    assert recorder.payload["think"] is False


async def test_local_ollama_adapts_a_small_model_request():
    recorder = install(Recorder(OLLAMA_STREAM,
                                headers={"content-type": "application/x-ndjson"},
                                stream=False))
    provider = Ollama(None, "http://localhost:11434", name="ollama-local",
                      think=False)
    await collect(provider, tools=TOOLS, max_tokens=16000)
    assert recorder.payload["options"] == {"num_predict": 1024, "num_ctx": 4096}
    assert provider.profile.tier == "compact"


def test_local_ollama_defaults_to_thinking(workdir):
    config = Config.load(workdir / "config.json")
    provider = registry.build("ollama-local", config)
    assert provider.think is True


async def test_ollama_models():
    install(Recorder(json.dumps({"models": [{"name": "llama3:8b"}, {"name": "qwen:7b"}]}),
                     headers={"content-type": "application/json"}, stream=False))
    provider = Ollama(None, "http://localhost:11434")
    assert await provider.models() == ["llama3:8b", "qwen:7b"]


async def test_ollama_no_models_is_an_error():
    install(Recorder(json.dumps({"models": []}),
                     headers={"content-type": "application/json"}, stream=False))
    with pytest.raises(ProviderError):
        await Ollama(None, "http://localhost:11434").models()


def test_ollama_message_shape():
    converted = to_ollama_messages(HISTORY, "sys")
    assert converted[0] == {"role": "system", "content": "sys"}
    assert converted[2]["tool_calls"][0]["function"]["arguments"] == {"command": "ls"}


# errors

@pytest.mark.parametrize("status,expected", [
    (401, AuthError), (403, AuthError), (429, RateLimitError),
    (404, ModelNotFound), (500, ProviderError), (400, ProviderError),
])
async def test_http_errors_map_to_types(status, expected):
    install(Recorder(json.dumps({"error": {"message": "nope"}}), status=status,
                     headers={"content-type": "application/json"}, stream=False))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    with pytest.raises(expected):
        await collect(provider)


async def test_rate_limit_carries_retry_after():
    install(Recorder("{}", status=429, headers={"retry-after": "7",
                                                "content-type": "application/json"},
                     stream=False))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    with pytest.raises(RateLimitError) as caught:
        await collect(provider)
    assert caught.value.retry_after == 7
    assert caught.value.retryable


async def test_connection_failure_names_the_host():
    def handler(request):
        raise httpx.ConnectError("refused")
    base.set_transport(httpx.MockTransport(handler))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    with pytest.raises(ConnectionFailed) as caught:
        await collect(provider)
    assert "api.openai.com" in str(caught.value)


async def test_error_inside_the_stream():
    install(Recorder(sse({"error": {"message": "overloaded"}})))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    with pytest.raises(ProviderError):
        await collect(provider)


async def test_garbage_stream_does_not_crash():
    install(Recorder("data: not json\n\ndata: [DONE]\n\n"))
    provider = OpenAICompatible("sk-x", "https://api.openai.com/v1")
    events = await collect(provider)
    assert isinstance(events[-1], base.Done)


def test_malformed_tool_arguments_are_repaired():
    assert base.loads_arguments('{"a": 1}') == {"a": 1}
    assert base.loads_arguments("") == {}
    assert base.loads_arguments('{"a": "b"') == {"a": "b"}
    with pytest.raises(ProviderError):
        base.loads_arguments("<<<>>>")


# registry

def test_every_provider_builds(monkeypatch):
    config = Config.load()
    for key in registry.ORDER:
        spec = registry.SPECS[key]
        config.set_provider(key, api_key="test-key-value",
                            base_url=spec.base_url or "https://example.com/v1")
        provider = registry.build(key, config)
        assert provider.protocol == spec.protocol
        assert provider.supports_tools == spec.supports_tools


def test_missing_key_is_reported():
    with pytest.raises(ProviderError):
        registry.build("chatgpt", Config.load())


def test_hosted_and_local_ollama_specs():
    spec = registry.spec("ollama")
    assert spec.label == "Ollama (API)"
    assert spec.needs_key is True
    assert spec.base_url == "https://ollama.com"
    assert spec.models
    assert "ollama-api" not in registry.SPECS

    local = registry.spec("ollama-local")
    assert local.label == "Ollama (local)"
    assert local.needs_key is False
    assert local.base_url == "http://localhost:11434"


def test_ollama_refuses_to_build_without_a_key():
    with pytest.raises(ProviderError):
        registry.build("ollama", Config.load())


def test_ollama_sends_the_key():
    config = Config.load()
    config.set_provider("ollama", api_key="ollama-test-key")
    provider = registry.build("ollama", config)
    assert provider.headers()["Authorization"] == "Bearer ollama-test-key"
    assert provider.base_url == "https://ollama.com"


async def test_ollama_falls_back_to_static_models():
    install(Recorder(json.dumps({"models": []}),
                     headers={"content-type": "application/json"}, stream=False))
    config = Config.load()
    config.set_provider("ollama", api_key="ollama-test-key")
    assert await registry.build("ollama", config).models()


@pytest.mark.parametrize("alias,expected", [
    ("openai", "chatgpt"), ("claude", "anthropic"), ("moonshot", "kimi"),
    ("google", "gemini"), ("deep", "deepseek"), ("anthropic", "anthropic"),
    ("ollama", "ollama"), ("ollama-api", "ollama"), ("ollama-cloud", "ollama"),
    ("ollama-local", "ollama-local"), ("local-ollama", "ollama-local"),
])
def test_aliases(alias, expected):
    assert registry.resolve_alias(alias) == expected


def test_unknown_alias():
    with pytest.raises(ProviderError):
        registry.resolve_alias("nonsense")


@pytest.mark.parametrize("raw", ["", "   ", "\n\t ", "short", "x" * 600, "abc\x00def"])
def test_bad_keys_rejected(raw):
    with pytest.raises(ProviderError):
        registry.validate_key("chatgpt", raw)


def test_key_whitespace_is_stripped():
    assert registry.validate_key("chatgpt", "  sk-abc123def\n") == "sk-abc123def"


@pytest.mark.parametrize("raw", ["", "example.com/v1", "ftp://x", "http://a b"])
def test_bad_base_urls_rejected(raw):
    with pytest.raises(ProviderError):
        registry.validate_base_url(raw)


def test_base_url_trailing_slash_stripped():
    assert registry.validate_base_url("https://x.dev/v1/ ") == "https://x.dev/v1"


def test_openai_message_conversion_drops_empty_content():
    converted = to_openai_messages(HISTORY, "")
    assistant = converted[1]
    assert assistant["content"] is None
    assert assistant["tool_calls"][0]["function"]["arguments"] == '{"command": "ls"}'
    assert converted[2]["tool_call_id"] == "c1"


async def test_ollama_reports_a_cut_off_reply():
    stream = "\n".join([
        json.dumps({"message": {"content": "I'll write it"}, "done": False}),
        json.dumps({"done": True, "done_reason": "length",
                    "prompt_eval_count": 4, "eval_count": 8192}),
    ]) + "\n"
    install(Recorder(stream, headers={"content-type": "application/x-ndjson"},
                     stream=False))
    events = await collect(Ollama(None, "http://localhost:11434"), tools=TOOLS)
    done = [e for e in events if isinstance(e, base.Done)][-1]
    assert done.reason == "length"


async def test_a_truncated_tool_call_is_not_called_a_tool_use():
    stream = "\n".join([
        json.dumps({"message": {"tool_calls": [
            {"function": {"name": "run_command", "arguments": {"command": "ls"}}}]},
            "done": False}),
        json.dumps({"done": True, "done_reason": "length"}),
    ]) + "\n"
    install(Recorder(stream, headers={"content-type": "application/x-ndjson"},
                     stream=False))
    events = await collect(Ollama(None, "http://localhost:11434"), tools=TOOLS)
    done = [e for e in events if isinstance(e, base.Done)][-1]
    assert done.reason == "length"


async def test_ollama_still_says_stop_normally():
    install(Recorder(OLLAMA_STREAM, headers={"content-type": "application/x-ndjson"},
                     stream=False))
    events = await collect(Ollama(None, "http://localhost:11434"), tools=TOOLS)
    assert [e for e in events if isinstance(e, base.Done)][-1].reason == "tool_use"


def _fail(body: str, code: int = 500, model: str = "qwen3:30b") -> str:
    response = httpx.Response(code, content=body.encode(),
                              request=httpx.Request("POST", "http://localhost:11434/api/chat"))
    with pytest.raises(ProviderError) as caught:
        base.raise_for_status(response, "localhost:11434", model)
    return caught.value.user_message()


TEMPLATE_BODY = json.dumps({"error": {"code": 500, "message":
    "\n------------\nWhile executing CallExpression at line 79, column 24 in source:\n"
    "{%- if multi_step_tool %}\n    {{- raise_exception('No user query found in messages.') }}\n"}})


def test_a_chat_template_failure_is_explained_in_plain_words():
    message = _fail(TEMPLATE_BODY)
    assert "qwen3:30b" in message
    assert "/model" in message
    assert "raise_exception" not in message
    assert "\n" not in message


def test_a_half_written_error_body_still_yields_the_reason():
    message = _fail(TEMPLATE_BODY[:220])
    assert "chat template" in message
    assert "{" not in message


def test_an_out_of_memory_failure_suggests_a_smaller_model():
    message = _fail(json.dumps({"error": "model requires more system memory (9.2 GiB)"}))
    assert "memory" in message and "/model" in message


def test_an_unknown_failure_keeps_a_short_readable_detail():
    message = _fail("Internal Server Error")
    assert message == "localhost:11434 failed while answering (error 500): Internal Server Error"


def test_an_empty_body_still_tells_the_user_what_to_do():
    assert _fail("").endswith("try again.")


def test_error_details_are_flattened_and_capped():
    detail = base.tidy_detail("\x1b[31mboom\x1b[0m\nsecond\tline\r\n" + "x" * 400)
    assert "\x1b" not in detail and "\n" not in detail and "\r" not in detail
    assert detail.startswith("boom second line")
    assert len(detail) <= base.DETAIL_LIMIT + 1


async def test_local_ollama_preserves_summary_prompt_and_model_context_limit():
    recorder = install(Recorder(OLLAMA_STREAM,
                                headers={"content-type": "application/x-ndjson"},
                                stream=False))
    provider = Ollama(None, "http://localhost:11434", name="ollama-local", think=False)
    provider._model_details["test-model"] = {"context_length": 2048}
    events = [event async for event in provider.stream(
        [Message.user("conversation")], "test-model", system="Summarise this conversation",
        tools=None, max_tokens=256)]
    assert events
    assert recorder.payload["messages"][0]["content"] == "Summarise this conversation"
    assert recorder.payload["options"]["num_ctx"] == 2048


async def test_ollama_does_not_execute_calls_from_an_incomplete_stream():
    partial = json.dumps({"message": {"tool_calls": [{"function": {
        "name": "write_file", "arguments": {"path": "a.txt", "content": "partial"}}}]}}) + "\n"
    install(Recorder(partial, headers={"content-type": "application/x-ndjson"}, stream=False))
    provider = Ollama(None, "http://localhost:11434", think=False)
    events = []
    with pytest.raises(ProviderError, match="before completion"):
        async for event in provider.stream(HISTORY, "test-model", tools=TOOLS):
            events.append(event)
    assert not any(isinstance(event, base.ToolCall) for event in events)
