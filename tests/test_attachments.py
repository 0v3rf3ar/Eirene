"""Model-driven image loading and provider-native conversion."""

from __future__ import annotations

import base64

import pytest

from eirene.core.attachments import prepare_image
from eirene.core.errors import ToolError
from eirene.providers.anthropic_compat import to_anthropic_messages
from eirene.providers.gemini import to_gemini_contents
from eirene.providers.openai_compat import to_openai_messages


def test_png_attachment_is_base64(workdir, box):
    body = b"\x89PNG\r\n\x1a\ncontent"
    (workdir / "image.png").write_bytes(body)
    image = prepare_image(box, "image.png")
    assert image["mime_type"] == "image/png"
    assert base64.b64decode(image["data"]) == body


def test_attachment_cannot_leave_sandbox(box):
    with pytest.raises(Exception):
        prepare_image(box, "../secret.txt")


def test_non_image_is_rejected(workdir, box):
    (workdir / "notes.txt").write_text("not pixels", encoding="utf-8")
    with pytest.raises(ToolError, match="requires a PNG"):
        prepare_image(box, "notes.txt")


def test_provider_converters_emit_native_image_shapes():
    attachment = {"mime_type": "image/png", "data": "YWJj", "name": "x.png"}
    messages = [{"role": "user", "content": "look", "attachments": [attachment]}]
    openai = to_openai_messages(messages, "")
    assert openai[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    anthropic = to_anthropic_messages(messages)
    assert anthropic[0]["content"][1]["source"]["data"] == "YWJj"
    gemini = to_gemini_contents(messages)
    assert gemini[0]["parts"][1]["inlineData"]["mimeType"] == "image/png"


async def test_read_image_tool_injects_vision_message(workdir, config):
    from eirene.core.agent import Agent
    from eirene.core.session import Session
    from eirene.providers.base import Done, TextDelta, ToolCall
    from eirene.tools.sandbox import Sandbox

    (workdir / "image.png").write_bytes(b"\x89PNG\r\n\x1a\ncontent")

    class Provider:
        supports_tools = True
        histories = []
        async def stream(self, messages, model, **kwargs):
            self.histories.append([dict(message) for message in messages])
            if len(self.histories) == 1:
                yield ToolCall("image", "read_image", {"path": "image.png"})
                yield Done("tool_use")
            else:
                yield TextDelta("I can see it")
                yield Done("stop")

    provider = Provider()
    agent = Agent(Session.create(workdir), config, Sandbox(workdir))
    agent.use(provider, "test", "vision-model")
    [event async for event in agent.run("inspect image.png")]
    await agent.close()
    second = provider.histories[1]
    assert second[-1]["role"] == "user"
    assert second[-1]["attachments"][0]["mime_type"] == "image/png"
