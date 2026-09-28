"""Codex app-server subscription provider."""

from __future__ import annotations

import json
import os
import stat
import sys

from eirene.providers.base import Done, PlanUpdate, TextDelta, ThinkingDelta, Usage
from eirene.providers.codex_subscription import CodexSubscription
from eirene.tools import activity


FAKE_SERVER = r'''#!{python}
import json, sys

logged_in = {logged_in}
for line in sys.stdin:
    message = json.loads(line)
    if "id" not in message:
        continue
    ident, method = message["id"], message.get("method")
    params = message.get("params") or {{}}
    if method == "initialize":
        result = {{}}
    elif method == "account/read":
        result = {{"account": ({{"type": "chatgpt", "email": "me@example.com",
                                  "planType": "plus"}} if logged_in else None)}}
    elif method == "account/login/start":
        logged_in = True
        result = {{"type": params["type"], "loginId": "login-1",
                  "verificationUrl": "https://auth.example/device", "userCode": "ABCD"}}
    elif method == "model/list":
        result = {{"data": [{{"id": "codex-a", "model": "codex-a"}},
                            {{"id": "codex-b", "model": "codex-b"}}]}}
    elif method == "thread/start":
        result = {{"thread": {{"id": "thread-1"}}}}
    elif method == "turn/start":
        result = {{"turn": {{"id": "turn-1", "status": "inProgress"}}}}
    elif method == "turn/interrupt":
        result = {{}}
    else:
        result = {{}}
    print(json.dumps({{"id": ident, "result": result}}), flush=True)
    if method == "account/login/start":
        print(json.dumps({{"method": "account/login/completed", "params": {{
            "loginId": "login-1", "success": True, "error": None}}}}), flush=True)
    if method == "turn/start":
        notices = [
          {{"method": "item/started", "params": {{
              "threadId": "thread-1", "turnId": "turn-1",
              "item": {{"id": "cmd-1", "type": "commandExecution",
                       "command": ["python", "-m", "pytest"]}}}}}},
          {{"method": "item/reasoning/summaryTextDelta", "params": {{
              "threadId": "thread-1", "turnId": "turn-1", "delta": "checking"}}}},
          {{"method": "item/agentMessage/delta", "params": {{
              "threadId": "thread-1", "turnId": "turn-1", "delta": "all done"}}}},
          {{"method": "thread/tokenUsage/updated", "params": {{
              "threadId": "thread-1", "turnId": "turn-1",
              "tokenUsage": {{"last": {{"inputTokens": 12, "outputTokens": 3}}}}}}}},
          {{"method": "turn/plan/updated", "params": {{
              "threadId": "thread-1", "turnId": "turn-1", "explanation": "next",
              "plan": [{{"step": "Inspect failure", "status": "completed"}},
                       {{"step": "Apply fix", "status": "inProgress"}}]}}}},
          {{"method": "item/completed", "params": {{
              "threadId": "thread-1", "turnId": "turn-1",
              "item": {{"id": "cmd-1", "type": "commandExecution",
                       "aggregatedOutput": {aggregated_output}}}}}}},
          {{"method": "turn/completed", "params": {{
              "threadId": "thread-1", "turn": {{"id": "turn-1", "status": "completed"}}}}}},
        ]
        for notice in notices:
            print(json.dumps(notice), flush=True)
'''


def fake_codex(tmp_path, logged_in=True, large_output=False):
    script = tmp_path / "fake_codex.py"
    script.write_text(FAKE_SERVER.format(
        python=sys.executable, logged_in="True" if logged_in else "False",
        aggregated_output=json.dumps("x" * 100_000 if large_output else "")),
        encoding="utf-8")
    if os.name == "nt":
        path = tmp_path / "fake-codex.cmd"
        path.write_text(f'@"{sys.executable}" "{script}" %*\n', encoding="utf-8")
    else:
        path = script
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return str(path)


async def test_subscription_account_models_and_stream(workdir, tmp_path):
    provider = CodexSubscription(binary=fake_codex(tmp_path))
    provider.set_context(workdir, "auto")
    seen = []
    listener = lambda: seen.extend(label for label, _ in activity.provider_commands())
    activity.subscribe(listener)
    try:
        assert (await provider.account())["planType"] == "plus"
        assert await provider.models() == ["codex-a", "codex-b"]
        events = [event async for event in provider.stream(
            [{"role": "user", "content": "fix it"}], "codex-a",
            system="be concise")]
        assert [e.text for e in events if isinstance(e, ThinkingDelta)] == ["checking"]
        assert [e.text for e in events if isinstance(e, TextDelta)] == ["all done"]
        usage = next(e for e in events if isinstance(e, Usage))
        assert (usage.input_tokens, usage.output_tokens) == (12, 3)
        plan = next(e for e in events if isinstance(e, PlanUpdate))
        assert plan.steps[1] == {"text": "Apply fix", "status": "in_progress"}
        assert isinstance(events[-1], Done)
        assert any("Codex: python -m pytest" in label for label in seen)
        assert activity.provider_commands() == []
    finally:
        activity.unsubscribe(listener)
        await provider.close()


async def test_large_command_completion_does_not_stall_stream(workdir, tmp_path):
    provider = CodexSubscription(
        binary=fake_codex(tmp_path, large_output=True), timeout=2)
    provider.set_context(workdir, "auto")
    try:
        events = [event async for event in provider.stream(
            [{"role": "user", "content": "run a noisy command"}], "codex-a")]
        assert isinstance(events[-1], Done)
        assert activity.provider_commands() == []
    finally:
        await provider.close()


async def test_subscription_device_login_is_codex_managed(tmp_path):
    provider = CodexSubscription(binary=fake_codex(tmp_path, logged_in=False))
    try:
        assert await provider.account() is None
        login = await provider.login("chatgptDeviceCode")
        assert login["verificationUrl"] == "https://auth.example/device"
        account = await provider.wait_for_login(login["loginId"])
        assert account["type"] == "chatgpt"
        assert account["email"] == "me@example.com"
    finally:
        await provider.close()


def test_mode_policies_are_safe_and_native(workdir):
    provider = CodexSubscription()
    provider.set_context(workdir, "auto")
    assert provider._turn_policy()["approvalPolicy"] == "on-request"
    assert provider._turn_policy()["sandboxPolicy"]["type"] == "workspaceWrite"
    provider.set_context(workdir, "manual")
    assert provider._turn_policy()["approvalPolicy"] == "untrusted", (
        "on-request lets Codex write inside the workspace without asking")
    provider.set_context(workdir, "plan")
    assert provider._turn_policy()["sandboxPolicy"]["type"] == "readOnly"


def test_mode_change_rotates_thread_for_fresh_instructions(workdir):
    provider = CodexSubscription()
    provider._thread_id = "old-thread"
    provider._system_sent = True
    provider.set_context(workdir, "auto")
    assert provider._thread_id == ""
    assert provider._system_sent is False


async def test_auto_mode_answers_tool_questions_without_prompting(workdir):
    provider = CodexSubscription()
    provider.set_context(workdir, "auto")
    result = await provider._approve_request({
        "method": "item/tool/requestUserInput",
        "params": {"questions": [{
            "id": "choice", "question": "Which approach?",
            "options": [{"label": "safe"}, {"label": "fast"}],
        }]},
    })
    assert result == {"answers": {"choice": {"answers": []}}}


async def test_manual_file_change_shows_native_diff_before_approval(workdir):
    seen = []

    async def approve(name, label, preview, reason):
        seen.append((name, label, preview, reason))
        return "yes"

    provider = CodexSubscription()
    provider.set_context(workdir, "manual", approve)
    provider._file_changes["edit-1"] = [{
        "path": str(workdir / "main.py"), "kind": "update",
        "diff": "--- main.py\n+++ main.py\n@@ -1 +1 @@\n-old\n+new",
    }]
    result = await provider._approve_request({
        "method": "item/fileChange/requestApproval",
        "params": {"itemId": "edit-1", "reason": "apply the fix"},
    })
    assert result == {"decision": "accept"}
    assert seen == [("native_apply_patch", "main.py",
                     "--- main.py\n+++ main.py\n@@ -1 +1 @@\n-old\n+new",
                     "apply the fix")]


async def test_a_codex_question_reaches_the_eirene_picker(workdir):
    asked = []

    async def choose(question, options):
        asked.append((question, list(options)))
        return "fast"

    provider = CodexSubscription()
    provider.set_context(workdir, "manual", None, choose)
    result = await provider._approve_request({
        "method": "item/tool/requestUserInput",
        "params": {"questions": [{
            "id": "choice", "question": "Which approach?",
            "options": [{"label": "safe", "description": "slower"},
                        {"label": "fast", "description": "riskier"}],
        }]},
    })
    assert result == {"answers": {"choice": {"answers": ["fast"]}}}
    assert asked == [("Which approach?", ["safe", "fast"])]


async def test_plan_mode_may_still_ask_the_user(workdir):
    async def choose(question, options):
        return options[0]

    provider = CodexSubscription()
    provider.set_context(workdir, "plan", None, choose)
    result = await provider._approve_request({
        "method": "item/tool/requestUserInput",
        "params": {"questions": [{"id": "q", "question": "which?",
                                  "options": [{"label": "a"}, {"label": "b"}]}]},
    })
    assert result == {"answers": {"q": {"answers": ["a"]}}}


async def test_plan_mode_declines_every_change(workdir):
    provider = CodexSubscription()
    provider.set_context(workdir, "plan", None, None)
    for method in ("item/fileChange/requestApproval",
                   "item/commandExecution/requestApproval"):
        decision = await provider._approve_request(
            {"method": method, "params": {"itemId": "x", "command": ["rm", "-rf", "."]}})
        assert decision == {"decision": "decline"}


async def test_an_unknown_server_request_is_declined(workdir):
    async def approve(name, label, preview, reason):
        raise AssertionError("unknown requests must not reach the user")

    provider = CodexSubscription()
    provider.set_context(workdir, "manual", approve, None)
    assert await provider._approve_request(
        {"method": "item/permissions/requestApproval", "params": {}}) == {
            "decision": "decline"}


def test_codex_work_items_become_visible_tool_cards(workdir):
    from eirene.providers.codex_subscription import _item_result, _item_tool

    command = _item_tool({"id": "c1", "type": "commandExecution",
                          "command": ["pytest", "-q"]}, workdir)
    assert (command.name, command.label, command.kind) == ("Bash", "pytest -q", "exec")

    change = _item_tool({"id": "f1", "type": "fileChange", "changes": [
        {"path": str(workdir / "pkg" / "main.py")}]}, workdir)
    assert (change.name, change.label, change.kind) == ("Edit", "pkg/main.py", "write")

    assert _item_tool({"id": "r1", "type": "reasoning"}, workdir) is None
    assert _item_tool({"type": "commandExecution"}, workdir) is None
    assert _item_result({"output": "5\n"}) == "5\n"
    assert _item_result({"type": "commandExecution"}) == ""


async def test_retry_notification_does_not_abort_turn(workdir, tmp_path, monkeypatch):
    import test_codex_subscription as fixture
    from eirene.providers.base import ConnectionStatus
    retry = '{{"method": "error", "params": {{"threadId": "thread-1", "turnId": "turn-1", "willRetry": true, "error": {{"message": "connection reset"}}}}}},'
    # Fake server source is Python, so its boolean must use Python spelling.
    retry = retry.replace("true", "True")
    monkeypatch.setattr(fixture, "FAKE_SERVER", FAKE_SERVER.replace("notices = [", "notices = [" + retry))
    provider = CodexSubscription(binary=fake_codex(tmp_path))
    provider.set_context(workdir, "auto")
    try:
        events = [e async for e in provider.stream([{"role": "user", "content": "go"}], "codex-a")]
        assert any(isinstance(e, ConnectionStatus) for e in events)
        assert any(isinstance(e, Done) for e in events)
    finally:
        await provider.close()
