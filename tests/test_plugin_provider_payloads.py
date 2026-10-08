"""All API provider factories carry plugin instructions and portable tool schemas."""
import json

import httpx
import pytest

from eirene.core.agent import Agent, Answer
from eirene.core.plugin_install import install
from eirene.core.session import Session
from eirene.providers import base, registry
from eirene.providers.local_profile import LocalProfile


@pytest.mark.parametrize("key", [key for key, spec in registry.SPECS.items()
    if spec.protocol not in {"codex-app-server", "claude-code-cli"}])
async def test_plugin_command_reaches_each_api_provider(key, config, box, tmp_path, monkeypatch):
    root = tmp_path / "workflow"
    (root / "commands").mkdir(parents=True)
    (root / "commands/review.md").write_text("Review the payment flow carefully.")
    install(str(root))
    config.set_provider(key, api_key="test-key-for-mock", base_url="https://mock.invalid/v1")
    requests = []
    def respond(request):
        requests.append(json.loads(request.content))
        protocol = registry.SPECS[key].protocol
        if protocol == "anthropic":
            data = ("event: content_block_delta\ndata: " + json.dumps({"type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "verified"}}) +
                "\n\nevent: message_stop\ndata: {\"type\":\"message_stop\"}\n\n")
        elif protocol == "gemini":
            data = "data: " + json.dumps({"candidates": [{"content": {"parts": [{"text": "verified"}]}, "finishReason": "STOP"}]}) + "\n\n"
        elif protocol == "ollama":
            data = json.dumps({"message": {"role": "assistant", "content": "verified"}, "done": True}) + "\n"
        else:
            data = "data: " + json.dumps({"choices": [{"delta": {"content": "verified"}, "finish_reason": "stop"}]}) + "\n\ndata: [DONE]\n\n"
        return httpx.Response(200, text=data)
    base.set_transport(httpx.MockTransport(respond))
    provider = registry.build(key, config)
    if key == "ollama-local":
        provider.profile = LocalProfile("compact", 3, 16, 4, 0)
        async def prepare(model):
            return 8192
        monkeypatch.setattr(provider, "prepare_context", prepare)
    agent = Agent(Session.create(box.root), config, box)
    agent.reload_skills()
    agent.use(provider, key, "chosen-model")
    try:
        events = [e async for e in agent.run("Review the payment flow carefully.", record_text="/workflow:review")]
        assert any(isinstance(event, Answer) and event.text == "verified" for event in events)
        assert len(requests) == 1
        payload = json.dumps(requests[0])
        assert "Review the payment flow carefully." in payload
        assert "/workflow:review" in payload
        if registry.SPECS[key].supports_tools:
            for name in ("load_skill", "load_plugin_resource", "delegate_tasks"):
                assert name in payload
        else:
            assert "tools" not in requests[0]
    finally:
        await agent.close()
        base.set_transport(None)
