"""Dropped files are inline tokens backed by a persistent, scoped reader."""
import base64
import shlex

import pytest
from textual import events

from eirene.app import Eirene
from eirene.core.attachments import (
    DEFAULT_ATTACHMENT_BYTES, attachment_path, dropped_paths, store_attachment,
)
from eirene.core.config import _merge_defaults
from eirene.core.errors import ToolError
from eirene.core.session import Session
from eirene.tools.registry import execute


class Recorder:
    supports_tools = True
    protocol = "test"

    def __init__(self):
        self.histories = []

    async def stream(self, messages, model, **kwargs):
        from eirene.providers.base import Done, TextDelta, ToolCall
        self.histories.append([dict(message) for message in messages])
        if len(self.histories) == 1:
            user = messages[-1]
            assert "read_attachment" in {tool["name"] for tool in kwargs["tools"]}
            for index, item in enumerate(user["files"]):
                yield ToolCall(str(index), "read_attachment", {"attachment_id": item["id"]})
            yield Done("tool_use")
        else:
            yield TextDelta("ok")
            yield Done("stop")


def test_drop_path_formats(workdir):
    first = workdir / "my notes.txt"
    second = workdir / "other.txt"
    first.touch()
    second.touch()
    assert dropped_paths(str(first), workdir) == [first]
    assert dropped_paths(shlex.join([str(first), str(second)]), workdir) == [first, second]
    assert dropped_paths(first.as_uri() + "\n" + second.as_uri(), workdir) == [first, second]
    assert dropped_paths(str(first).replace(" ", "\\ "), workdir) == [first]
    assert dropped_paths("./other.txt", workdir) == [second]
    assert dropped_paths("explain " + str(second), workdir) == []
    assert dropped_paths(str(second) + " /missing/file", workdir) == []
    assert dropped_paths("file://remote" + str(second), workdir) == []
    assert dropped_paths(str(workdir), workdir) == []


def test_size_limit_and_binary_snapshot(workdir):
    assert _merge_defaults({})["max_attachment_bytes"] == DEFAULT_ATTACHMENT_BYTES == 20_000_000
    assert _merge_defaults({"max_attachment_bytes": 30_000_000})["max_attachment_bytes"] == 30_000_000
    assert _merge_defaults({"max_attachment_bytes": "invalid"})["max_attachment_bytes"] == DEFAULT_ATTACHMENT_BYTES
    target = workdir / "data.bin"
    target.write_bytes(b"\x00\xff\x01")
    item = store_attachment(target, 3)
    target.write_bytes(b"changed")
    assert attachment_path(item["id"]).read_bytes() == b"\x00\xff\x01"
    with pytest.raises(ToolError, match="limit"):
        store_attachment(target, 3)


async def test_inline_tokens_and_model_attachment_tool(workdir, outside):
    text = outside / "secret.txt"
    image = workdir / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\ncontent")
    app = Eirene(workdir)
    recorder = Recorder()
    async with app.run_test() as pilot:
        app.agent.use(recorder, "test", "test-model")
        app.prompt.value = "inspect these "
        app.set_focus(None)
        app.post_message(events.Paste(shlex.join([str(text), str(image)])))
        await pilot.pause()
        assert app.prompt.text == "inspect these [secret.txt][image.png]"
        assert len(app.prompt._files) == 2
        line = app.prompt.get_line(0)
        for token in app.prompt._files:
            assert line.get_style_at_offset(app.console, line.plain.index(token)).bold
            assert line.get_style_at_offset(app.console, line.plain.index(token)).italic
        assert not recorder.histories
        assert not app.sandbox.contains(text)
        # The stored snapshot must survive changes to the original.
        text.write_text("changed source")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert app.turn.done()
        initial = recorder.histories[0][-1]
        assert "inspect these" in initial["content"]
        assert "do not read" not in initial["content"]
        assert len(initial["files"]) == 2
        from eirene.ui.chat import UserBlock
        sent = next(iter(app.transcript.query(UserBlock)))._Static__content
        for item in initial["files"]:
            style = sent.get_style_at_offset(app.console, sent.plain.index(item["token"]))
            assert style.bold and style.italic
        results = [m for m in app.session.messages if m["role"] == "tool"]
        assert any("do not read" in m["content"] for m in results)
        from eirene.ui.chat import ToolBlock
        cards = list(app.transcript.query(ToolBlock))
        assert cards
        assert all(card.hide_output for card in cards)
        assert all("do not read" not in card._Static__content.plain for card in cards)
        vision = next(m for m in app.session.messages if m.get("attachments"))
        assert base64.b64decode(vision["attachments"][0]["data"]) == image.read_bytes()
        assert not app.prompt._files
        app.prompt.value = "next"
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert recorder.histories[-1][-1]["content"] == "next"
        assert not recorder.histories[-1][-1].get("files")
    resumed = Session.resume(app.session.id)
    assert len(resumed.file_attachments) == 2
    resumed.close()


@pytest.mark.parametrize("name,label", [
    ("read_attachment", "reading attachment"),
    ("mcp__eirene_attachments__read_attachment", "reading attachment"),
    ("MCP", "read_attachment"),
    ("read_file", "notes.txt"),
    ("Read", "notes.txt"),
    ("web_search", "example search"),
    ("WebSearch", "example search"),
    ("MCP", "read_file"),
    ("mcp__search__web_search", "example search"),
])
async def test_attachment_activity_hides_content_and_keeps_errors_visible(name, label, workdir):
    from eirene.ui.chat import ToolBlock
    app = Eirene(workdir)
    async with app.run_test():
        card = await app.push(ToolBlock(name, label))
        card.feed("private attachment contents")
        card.flush()
        assert "private attachment contents" not in card._Static__content.plain
        card.finish("private attachment contents", False, 0)
        card.flush()
        assert "private attachment contents" not in card._Static__content.plain
        assert label in card._Static__content.plain
        card.finish("attachment is not available in this conversation", True, 0)
        card.flush()
        assert "attachment is not available" in card._Static__content.plain


async def test_remove_token_and_undo(workdir):
    target = workdir / "notes.txt"
    target.write_text("notes")
    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app.agent.use(Recorder(), "test", "test-model")
        app.prompt.post_message(events.Paste(str(target)))
        await pilot.pause()
        app.prompt.history.checkpoint()
        await pilot.press("backspace")
        assert app.prompt.text == ""
        await pilot.press("ctrl+z")
        assert app.prompt.text == "[notes.txt]"
        await pilot.press("backspace")
        app.prompt.insert("only text")
        await pilot.press("enter")
        for _ in range(40):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert not app.session.file_attachments


async def test_no_connection_preserves_attachment_and_draft(workdir):
    target = workdir / "notes.txt"
    target.write_text("notes")
    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app.prompt.value = "explain "
        app.prompt.post_message(events.Paste(str(target)))
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert app.prompt.text == "explain [notes.txt]"
        assert app.prompt._files


async def test_configured_limit_rejects_drop(workdir):
    target = workdir / "notes.txt"
    target.write_bytes(b"a" * 11)
    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app.config.set("max_attachment_bytes", 10)
        app.prompt.post_message(events.Paste(str(target)))
        await pilot.pause()
        assert not app.prompt._files and not app.prompt.text
        app.config.set("max_attachment_bytes", 11)
        app.prompt.post_message(events.Paste(str(target)))
        await pilot.pause()
        assert app.prompt.text == "[notes.txt]"


async def test_reader_scope_and_continuation(workdir, box):
    target = workdir / "data.txt"
    target.write_text("hello world")
    item = store_attachment(target)
    with pytest.raises(ToolError, match="conversation"):
        await execute("read_attachment", {"attachment_id": item["id"]}, box)
    available = {item["id"]: item}
    first = await execute("read_attachment", {"attachment_id": item["id"], "limit": 5},
                          box, file_attachments=available)
    assert "hello" in first and "offset=5" in first
    second = await execute("read_attachment", {"attachment_id": item["id"], "offset": 5},
                           box, file_attachments=available)
    assert " world" in second and "(end of attachment)" in second
    target.write_bytes(b"\x00\xff")
    binary = store_attachment(target)
    result = await execute("read_attachment", {"attachment_id": binary["id"]}, box,
                           file_attachments={binary["id"]: binary})
    assert "(base64)" in result and "AP8=" in result
    with pytest.raises(ToolError, match="conversation"):
        await execute("read_attachment", {"attachment_id": "../../secret"}, box,
                      file_attachments=available)


def test_steering_preserves_file_attachments(workdir, config, box):
    from eirene.core.agent import Agent
    target = workdir / "notes.txt"
    target.write_text("notes")
    item = store_attachment(target)
    session = Session.create(workdir)
    agent = Agent(session, config, box)
    agent.steer("look [notes.txt]", files=[item])
    assert agent._consume_input()
    assert session.messages[-1]["files"] == [item]
    assert session.file_attachments[item["id"]] == item
    session.close()


def test_native_attachment_reader_protocol(workdir):
    import json
    import os
    import subprocess
    from eirene.providers.attachment_reader import call, definition
    target = workdir / "notes.txt"
    target.write_text("native attachment contents")
    item = store_attachment(target)
    session = Session.create(workdir)
    session.add_user("inspect [notes.txt]", files=[item])
    session.close()
    other = Session.create(workdir)
    other.add_user("no files")
    other.close()
    with pytest.raises(ToolError, match="conversation"):
        call(other.id, {"attachment_id": item["id"]})
    command = definition(session.id)
    requests = [
        {"id": 1, "method": "initialize"},
        {"id": 2, "method": "tools/list"},
        {"id": 3, "method": "tools/call", "params": {
            "name": "read_attachment", "arguments": {"attachment_id": item["id"]}}},
    ]
    result = subprocess.run([command["command"], *command["args"]],
                            env={**os.environ, **command["env"]},
                            input="".join(json.dumps(req) + "\n" for req in requests),
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line)["result"] for line in result.stdout.splitlines()]
    assert responses[1]["tools"][0]["name"] == "read_attachment"
    assert "native attachment contents" in responses[2]["content"][0]["text"]


async def test_sectional_reads_share_one_card_per_attachment_live_and_replayed(workdir):
    from eirene.providers.base import Done, TextDelta, ToolCall
    from eirene.ui.chat import ToolBlock

    first = workdir / "first.txt"
    second = workdir / "second.txt"
    first.write_text("abcdefghi")
    second.write_text("123456789")

    class SectionReader:
        supports_tools = True
        protocol = "test"
        calls = 0

        async def stream(self, messages, model, **kwargs):
            if self.calls < 3:
                files = next(message["files"] for message in messages if message.get("files"))
                for index, item in enumerate(files):
                    yield ToolCall(f"page-{self.calls}-{index}", "read_attachment", {
                        "attachment_id": item["id"], "offset": self.calls * 3, "limit": 3,
                    })
                self.calls += 1
                yield Done("tool_use")
            else:
                yield TextDelta("read both files")
                yield Done("stop")

    app = Eirene(workdir)
    async with app.run_test() as pilot:
        app.agent.use(SectionReader(), "test", "test-model")
        app.prompt.post_message(events.Paste(shlex.join([str(first), str(second)])))
        await pilot.pause()
        await pilot.press("enter")
        for _ in range(60):
            await pilot.pause()
            if app.turn and app.turn.done():
                break
        assert app.turn.done()
        assert len([m for m in app.session.messages if m["role"] == "tool"]) == 6
        cards = list(app.transcript.query(ToolBlock))
        assert len(cards) == 2
        assert all(card.finished and not card.is_error and card.hide_output for card in cards)
        app.transcript.reset()
        await pilot.pause()
        await app.replay_transcript()
        assert len(list(app.transcript.query(ToolBlock))) == 2
