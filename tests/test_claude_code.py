"""Claude Code headless subscription provider."""

from __future__ import annotations

import stat
import os
import sys
from pathlib import Path

from eirene.providers.base import Done, PlanUpdate, TextDelta, ThinkingDelta, Usage
from eirene.providers.claude_code import ClaudeCode, _system_prompt
from eirene.providers.permission_proxy import (ASK_TOOL, TOOL_SCHEMAS,
                                               PermissionBroker, describe_change)
from eirene.tools import activity
from eirene.tools.registry import CHAT_OPTION


FAKE_CLAUDE = r'''#!{python}
import json, sys

if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": {logged_in}, "authMethod": "claude.ai"}}))
    raise SystemExit(0)

events = [
    {{"type": "system", "subtype": "init", "session_id": "session-1"}},
    {{"type": "stream_event", "session_id": "session-1", "event": {{
        "type": "content_block_delta", "delta": {{"type": "thinking_delta",
        "thinking": "checking"}}}}}},
    {{"type": "stream_event", "session_id": "session-1", "event": {{
        "type": "content_block_delta", "delta": {{"type": "text_delta",
        "text": "fixed"}}}}}},
    {{"type": "assistant", "session_id": "session-1", "message": {{
        "content": [{{"type": "text", "text": "fixed"}},
        {{"type": "tool_use", "id": "bash-1", "name": "Bash",
          "input": {{"command": "python -m pytest"}}}}, {{"type": "tool_use",
        "name": "TodoWrite", "input": {{"todos": [
            {{"content": "Inspect", "status": "completed"}},
            {{"content": "Verify", "status": "in_progress"}}]}}}}],
        "usage": {{"input_tokens": 10, "output_tokens": 4}}}}}},
    {{"type": "user", "session_id": "session-1", "message": {{
        "content": [{{"type": "tool_result", "tool_use_id": "bash-1",
                     "content": "passed"}}]}}}},
    {{"type": "result", "subtype": "success", "is_error": False,
      "session_id": "session-1", "result": "fixed"}},
]
for event in events:
    print(json.dumps(event), flush=True)
'''


def fake_claude(tmp_path, logged_in=True):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE.format(
        python=sys.executable, logged_in="True" if logged_in else "False"),
        encoding="utf-8")
    if os.name == "nt":
        path = tmp_path / "fake-claude.cmd"
        path.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        path = script
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


async def test_account_models_and_stream(workdir, tmp_path):
    provider = ClaudeCode(binary=fake_claude(tmp_path))
    provider.set_context(workdir, "auto", approve=lambda *args: _approve_native())
    assert (await provider.account())["authMethod"] == "claude.ai"
    assert await provider.models() == ["sonnet", "opus", "haiku"]
    seen = []
    listener = lambda: seen.extend(label for label, _ in activity.provider_commands())
    activity.subscribe(listener)
    try:
        events = [event async for event in provider.stream(
            [{"role": "user", "content": "fix it"}], "sonnet", system="Eirene")]
    finally:
        activity.unsubscribe(listener)
    assert [e.text for e in events if isinstance(e, ThinkingDelta)] == ["checking"]
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["fixed"]
    assert next(e for e in events if isinstance(e, Usage)).total == 14
    plan = next(e for e in events if isinstance(e, PlanUpdate))
    assert plan.steps[1] == {"text": "Verify", "status": "in_progress"}
    assert isinstance(events[-1], Done)
    assert provider._session_id == "session-1"
    assert any("Claude Code: python -m pytest" in label for label in seen)
    assert activity.provider_commands() == []


def test_modes_and_mode_change_reset_session(workdir):
    provider = ClaudeCode()
    provider.set_context(workdir, "manual")
    assert provider._permission_mode() == "manual"
    provider._session_id = "old"
    provider.set_context(workdir, "auto", approve=lambda *args: _approve_native())
    assert provider._permission_mode() == "auto"
    assert provider._session_id == ""
    provider.set_context(workdir, "plan")
    assert provider._permission_mode() == "plan"


def test_claude_write_and_edit_permissions_include_diffs(workdir):
    (workdir / "main.py").write_text("old\n", encoding="utf-8")
    name, label, preview = describe_change(
        "Edit", {"file_path": str(workdir / "main.py"),
                 "old_string": "old", "new_string": "new"}, workdir)
    assert (name, label) == ("native_edit_file", str(workdir / "main.py"))
    assert "-old" in preview and "+new" in preview


async def test_claude_permission_broker_waits_for_eirene_approval(workdir):
    seen = []

    async def approve(name, label, preview, reason):
        seen.append((name, label, preview))
        return "yes"

    broker = PermissionBroker(workdir, approve)
    decision = await broker._decide(
        "Write", {"file_path": "new.py", "content": "print('ok')\n"})
    assert decision["behavior"] == "allow"
    assert decision["updatedInput"]["content"] == "print('ok')\n"
    assert seen[0][0:2] == ("native_write_file", "new.py")
    assert "+print('ok')" in seen[0][2]


def test_the_permission_server_runs_from_any_working_directory(workdir):
    broker = PermissionBroker(workdir, None)
    command, args, environment = broker.command()
    assert args[:2] == ["-m", "eirene"]
    assert Path(environment["PYTHONPATH"].split(os.pathsep)[0], "eirene").is_dir()


async def test_a_claude_question_reaches_the_eirene_picker(workdir):
    asked = []

    async def choose(question, options):
        asked.append((question, list(options)))
        return options[1]

    broker = PermissionBroker(workdir, None, choose)
    reply = await broker._answer("tabs or spaces?", ["tabs", "spaces", "  "])
    assert reply == {"answer": "spaces"}
    assert asked == [("tabs or spaces?", ["tabs", "spaces"])]


async def test_a_question_with_nobody_watching_tells_claude_to_decide(workdir):
    broker = PermissionBroker(workdir, None, None)
    assert "decide yourself" in (await broker._answer("which?", ["a", "b"]))["answer"]


async def test_wanting_to_talk_it_through_stops_the_question(workdir):
    async def choose(question, options):
        return CHAT_OPTION

    broker = PermissionBroker(workdir, None, choose)
    assert "plain text" in (await broker._answer("which?", ["a", "b"]))["answer"]


async def test_the_ask_tool_never_needs_its_own_approval(workdir):
    async def approve(name, label, preview, reason):
        raise AssertionError("asking must not raise a permission prompt")

    broker = PermissionBroker(workdir, approve)
    assert (await broker._decide(ASK_TOOL, {"question": "which?"}))["behavior"] == "allow"


async def test_plan_mode_denies_tools_the_user_never_gated(workdir):
    broker = PermissionBroker(workdir, None, None, "deny")
    decision = await broker._decide("Write", {"file_path": "x.py", "content": "x"})
    assert decision["behavior"] == "deny"
    assert (await broker._decide(ASK_TOOL, {}))["behavior"] == "allow"


def test_questions_are_offered_outside_auto_mode(workdir):
    async def choose(question, options):
        return options[0]

    provider = ClaudeCode()
    provider.set_context(workdir, "manual", None, choose)
    assert provider.choose is choose
    assert ASK_TOOL in _system_prompt("base prompt", True)
    assert _system_prompt("base prompt", False) == "base prompt"


def test_the_ask_schema_matches_what_eirene_can_show():
    schema = next(tool for tool in TOOL_SCHEMAS if tool["name"] == "ask_user")
    assert schema["inputSchema"]["required"] == ["question", "options"]


async def test_claude_tool_work_reaches_the_transcript(workdir, tmp_path):
    from eirene.providers.base import ProviderTool

    provider = ClaudeCode(binary=fake_claude(tmp_path))
    provider.set_context(workdir, "auto", approve=lambda *args: _approve_native())
    events = [event async for event in provider.stream(
        [{"role": "user", "content": "fix it"}], "sonnet", system="Eirene")]
    shown = [event for event in events if isinstance(event, ProviderTool)]
    assert [(t.name, t.label, t.kind, t.finished) for t in shown] == [
        ("Bash", "python -m pytest", "exec", False),
        ("Bash", "python -m pytest", "exec", True)]
    assert shown[1].result == "passed" and not shown[1].is_error


def test_claude_tool_labels_show_the_detail_that_matters(workdir):
    from eirene.providers.claude_code import _tool_kind, _tool_label

    cases = [
        ("Read", {"file_path": str(workdir / "a" / "b.py")}, "read", "a/b.py"),
        ("Edit", {"file_path": str(workdir / "x.py"), "old_string": "a"}, "write", "x.py"),
        ("Bash", {"command": "pytest  -q"}, "exec", "pytest -q"),
        ("Grep", {"pattern": "TODO"}, "read", "TODO"),
        ("WebFetch", {"url": "https://example.com"}, "read", "https://example.com"),
        ("Mystery", {}, "exec", "Mystery"),
    ]
    for name, arguments, kind, label in cases:
        assert _tool_kind(name) == kind, name
        assert _tool_label(name, arguments, workdir) == label, name


def test_a_claude_tool_result_is_flattened_for_display():
    from eirene.providers.claude_code import RESULT_LIMIT, _result_text

    assert _result_text("plain") == "plain"
    assert _result_text([{"type": "text", "text": "one"},
                         {"type": "image"}, {"type": "text", "text": "two"}]) == "one\ntwo"
    assert _result_text(None) == ""
    assert len(_result_text("x" * 900)) == 900
    assert len(_result_text("x" * (RESULT_LIMIT + 1))) == RESULT_LIMIT


async def test_the_permission_bridge_stays_out_of_the_transcript(workdir, tmp_path):
    from eirene.providers.base import ProviderTool
    from eirene.providers.permission_proxy import ASK_TOOL

    script = tmp_path / "bridge_claude.py"
    script.write_text(FAKE_CLAUDE.format(python=sys.executable, logged_in="True")
                      .replace('"name": "Bash"', f'"name": "{ASK_TOOL}"'),
                      encoding="utf-8")
    if os.name == "nt":
        binary = tmp_path / "bridge.cmd"
        binary.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        binary = script
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

    provider = ClaudeCode(binary=str(binary))
    provider.set_context(workdir, "auto", approve=lambda *args: _approve_native())
    events = [event async for event in provider.stream(
        [{"role": "user", "content": "go"}], "sonnet", system="")]
    shown = [event for event in events if isinstance(event, ProviderTool)]
    assert not any(tool.name.startswith("mcp__eirene__") for tool in shown), \
        "Eirene's own bridge is plumbing, not the model's work"


def test_a_write_carries_the_diff_it_is_about_to_apply(workdir):
    from eirene.providers.claude_code import _change_preview

    (workdir / "main.c").write_text("int old(void) { return 1; }\n", encoding="utf-8")
    update = _change_preview("Edit", {"file_path": str(workdir / "main.c"),
                                      "old_string": "return 1", "new_string": "return 2"},
                             workdir)
    assert "-int old(void) { return 1; }" in update
    assert "+int old(void) { return 2; }" in update

    create = _change_preview("Write", {"file_path": str(workdir / "new.c"),
                                       "content": "int main(void) { return 0; }\n"},
                             workdir)
    assert "+int main(void) { return 0; }" in create

    assert _change_preview("Bash", {"command": "ls"}, workdir) == ""
    assert _change_preview("Read", {"file_path": str(workdir / "main.c")}, workdir) == ""
    outside = _change_preview("Write", {"file_path": "/etc/passwd", "content": "x"},
                              workdir)
    assert outside == "x", "a path outside falls back to the content, never raises"


async def test_api_retry_is_reported_without_restarting(workdir, tmp_path, monkeypatch):
    import test_claude_code as fixture
    from eirene.providers.base import ConnectionStatus
    retry = '{{"type": "system", "subtype": "api_retry", "attempt": 2, "retry_delay_ms": 1200}},'
    monkeypatch.setattr(fixture, "FAKE_CLAUDE", FAKE_CLAUDE.replace("events = [", "events = [" + retry))
    provider = ClaudeCode(binary=fake_claude(tmp_path))
    provider.set_context(workdir, "auto", approve=lambda *args: _approve_native())
    try:
        events = [e async for e in provider.stream([{"role": "user", "content": "go"}], "claude")]
        assert any(isinstance(e, ConnectionStatus) and "attempt 2" in e.text for e in events)
        assert any(isinstance(e, Done) for e in events)
    finally:
        await provider.close()


async def _approve_native():
    return "yes"
