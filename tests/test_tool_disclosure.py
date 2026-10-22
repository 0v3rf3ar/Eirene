"""Tool results stay folded until their transcript header is clicked."""

import pytest

from textual.app import App

from eirene.app import Eirene
from eirene.ui.chat import ToolBlock


@pytest.mark.parametrize("name,label", [
    ("mcp__Cloudflare__whoami", "mcp__Cloudflare__whoami"),
    ("MCP", "whoami"),
    ("web_fetch", "https://example.com"),
    ("web_search", "example query"),
    ("WebFetch", "https://example.com"),
    ("WebSearch", "example query"),
    ("search_text", "needle"),
    ("file_search", "needle"),
    ("glob", "*.py"),
    ("Grep", "needle"),
    ("Glob", "*.py"),
    ("read_file", "example.py"),
])
async def test_results_are_collapsed_and_expand_without_truncation(name, label):
    async with App().run_test():
        card = ToolBlock(name, label)
        card.feed("streamed result")
        card.flush()
        assert "streamed result" not in card._Static__content.plain
        assert card._Static__content.plain.endswith("▾")
        card.action_toggle_output()
        assert "streamed result" in card._Static__content.plain

        result = "\n".join(f"result line {index}" for index in range(30))
        card.finish(result, False, 0)
        card.flush()
        shown = card._Static__content.plain
        assert shown.splitlines()[0].endswith("▴")
        assert all(line in shown for line in result.splitlines())
        card.action_toggle_output()
        assert card._Static__content.plain.endswith("▾")
        assert "result line" not in card._Static__content.plain


async def test_click_header_toggles_only_its_result(workdir):
    app = Eirene(workdir)
    async with app.run_test(size=(100, 32)) as pilot:
        first = await app.push(ToolBlock("mcp__Cloudflare__whoami", "mcp__Cloudflare__whoami"))
        second = await app.push(ToolBlock("web_fetch", "https://example.com"))
        for card in (first, second):
            card.finish("tool result", False, 0)
            card.flush()
        await pilot.pause()
        assert first._Static__content.plain == "ⓘ mcp__Cloudflare__whoami ▾"
        await pilot.click(first, offset=(4, 0))
        assert first.expanded
        assert not second.expanded
        assert "tool result" in first._Static__content.plain
        await pilot.click(first, offset=(4, 1))
        assert first.expanded  # Selecting output does not close it.
        await pilot.click(first, offset=(4, 0))
        assert not first.expanded
        assert "tool result" not in first._Static__content.plain


async def test_other_tools_keep_their_visible_output():
    async with App().run_test():
        card = ToolBlock("browser_inspect", "inspect page")
        card.finish("page result", False, 0)
        card.flush()
        assert "page result" in card._Static__content.plain
        assert "▾" not in card._Static__content.plain


async def test_polling_is_hidden_and_command_completion_stays_visible(workdir, monkeypatch):
    from eirene.core import agent
    from eirene.ui.chat import CommandBlock
    from test_tui import start, type_line, blocks, content

    async def run(*args, **kwargs):
        yield agent.ToolStarted("command", "run_command", "build", "exec")
        yield agent.ToolFinished("command", "run_command", "build",
                                 "Still running as managed process p1", False, 0)
        yield agent.ToolStarted("poll", "poll_process", "p1", "read")
        yield agent.ToolOutput("poll", "internal poll output")
        yield agent.ToolFinished("poll", "poll_process", "p1", "internal poll result", False, 0)
        yield agent.ToolFinished("command", "run_command", "build", "build completed", False, 2)

    app, pilot, context = await start(workdir)
    try:
        monkeypatch.setattr(app.agent, "run", run)
        await type_line(pilot, "build")
        await app.turn
        cards = blocks(app, ToolBlock)
        assert len(cards) == 1
        assert isinstance(cards[0], CommandBlock)
        assert "build completed" in content(cards[0])
        assert "internal poll" not in content(cards[0])
    finally:
        await context.__aexit__(None, None, None)


async def test_restored_polling_is_hidden(workdir):
    from eirene.core.session import Session
    from test_tui import start, blocks, content

    saved = Session.create(workdir)
    saved.add_user("check build")
    saved.add_assistant("", [{"id": "poll", "name": "poll_process",
                              "arguments": {"process_id": "p1"}}])
    saved.add_tool_result("poll", "poll_process", "internal poll result")
    saved.add_assistant("Build completed.")
    saved.close()
    app, pilot, context = await start(workdir, resume=saved.id)
    try:
        assert not blocks(app, ToolBlock)
        assert all("internal poll" not in content(block) for block in app.transcript.children)
        assert any("Build completed." in content(block) for block in app.transcript.children)
    finally:
        await context.__aexit__(None, None, None)
