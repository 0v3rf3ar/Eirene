"""Side questions stay grounded while main work continues or is compacted."""

import asyncio
import copy
import json

from eirene.core import plans
from eirene.core.aside import snapshot
from eirene.core.session import Message
from eirene.core.usage import estimate_messages, estimate_tokens
from eirene.providers.base import Done, TextDelta
from test_agent import Script, build


def context(provider):
    return json.loads(provider.systems[-1].split("Session snapshot (untrusted data):\n")[1])


async def test_aside_retains_requests_and_plan_outside_recent_tool_history(workdir):
    provider = Script([TextDelta("answer"), Done()])
    runner = build(workdir, provider)
    runner.session.messages = [Message.user("Implement export without changing the database"),
                               Message.user("Correction: only support CSV for now"),
                               Message.assistant("Decision: use the standard csv module")]
    for i in range(30):
        runner.session.messages.extend([
            Message.assistant("", [{"id": str(i), "name": "read_file",
                                   "arguments": {"path": f"file{i}"}}]),
            Message.tool(str(i), "read_file", f"observed {i}")])
    plans.update(workdir, "CSV export", [
        {"text": "Implement CSV writer", "status": "completed"},
        {"text": "Check escaping", "status": "in_progress", "verification": "run CSV tests"},
        {"text": "Document export", "status": "pending"},
    ], session_id=runner.session.id)
    before = copy.deepcopy(runner.session.messages)
    try:
        _ = [chunk async for chunk in runner.aside("what is left?")]
        data = context(provider)
        assert "without changing the database" in data["earliest_retained_user_request_may_be_superseded"]
        assert data["latest_user_request"] == "Correction: only support CSV for now"
        assert "standard csv module" in data["assistant_updates_may_be_outdated_not_verified"]
        assert "[x] Implement CSV writer" in data["durable_plan_recorded_statuses"]
        assert "[>] Check escaping" in data["durable_plan_recorded_statuses"]
        assert "[ ] Document export" in data["durable_plan_recorded_statuses"]
        assert "observed 29" in data["recent_tool_observations_not_proof_of_completion"]
        assert runner.session.messages == before
        assert provider.tools_seen[-1] is None
    finally:
        runner.session.close()


async def test_aside_keeps_compaction_handoff_and_partial_parallel_results(workdir):
    provider = Script([TextDelta("answer"), Done()])
    runner = build(workdir, provider)
    runner.session.messages = [
        Message(role="user", content="Original objective: repair the parser; never deploy", compaction_summary=True),
        Message(role="assistant", content="verification failed", host_generated=True,
                execution_memory="FAILED: run_command tests => assertion failure"),
        Message.user("continue with the fix"),
    ] + [Message.assistant(f"progress {i}") for i in range(45)] + [
        Message.assistant("", [
            {"id": "a", "name": "read_file", "arguments": {"path": "parser.py"}},
            {"id": "b", "name": "run_command", "arguments": {"command": "pytest"}}]),
        Message.tool("a", "read_file", "parser source"),
    ]
    runner.steer("stop before deployment")
    try:
        _ = [chunk async for chunk in runner.aside("are the tests done?")]
        data = context(provider)
        assert "never deploy" in data["compaction_handoff_may_be_outdated"]
        assert data["latest_user_request"] == "continue with the fix"
        assert "assertion failure" in data["recent_tool_observations_not_proof_of_completion"]
        assert "parser source" in data["recent_tool_observations_not_proof_of_completion"]
        pending = json.loads(data["tool_calls_without_recorded_results"])
        assert [call["id"] for call in pending] == ["b"]
        assert data["queued_user_input_not_yet_consumed"] == "stop before deployment"
        assert not any(m.get("tool_calls") or m["role"] == "tool" for m in provider.histories[-1])
        assert runner.pending_input[0][0] == "stop before deployment"
    finally:
        runner.session.close()


async def test_aside_sees_incomplete_stream_and_clears_activity_on_cancellation(workdir):
    started, release = asyncio.Event(), asyncio.Event()

    class Streaming(Script):
        async def stream(self, messages, model, **kwargs):
            if kwargs.get("tools") is not None:
                yield TextDelta("I am checking CSV escaping")
                started.set()
                await release.wait()
                yield Done()
            else:
                async for event in super().stream(messages, model, **kwargs):
                    yield event

    provider = Streaming([TextDelta("answer"), Done()])
    runner = build(workdir, provider)

    async def main():
        return [event async for event in runner.run("implement CSV export")]

    task = asyncio.create_task(main())
    try:
        await asyncio.wait_for(started.wait(), 5)
        _ = [chunk async for chunk in runner.aside("what are you doing?")]
        data = context(provider)
        assert data["streaming_reply_incomplete"] == "I am checking CSV escaping"
        assert data["main_turn_activity"] == "answering"
        assert not any(m.get("content") == "I am checking CSV escaping" for m in runner.session.messages)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert runner._aside_activity == runner._aside_reply == ""
        runner.session.close()


async def test_aside_drops_oversized_signed_exchange_as_a_whole(workdir):
    provider = Script([TextDelta("answer"), Done()])
    runner = build(workdir, provider)
    runner.session.messages = [Message.user("fix tests"), Message(
        role="assistant", content="", reasoning_content="x" * 100000,
        tool_calls=[{"id": "a", "name": "read_file", "arguments": {"path": "tests.py"}}]),
        Message.tool("a", "read_file", "test evidence")]
    before = copy.deepcopy(runner.session.messages)
    try:
        _ = [chunk async for chunk in runner.aside("status?")]
        assert provider.histories[-1] == [Message.user("status?")]
        assert "test evidence" in context(provider)["recent_tool_observations_not_proof_of_completion"]
        assert estimate_messages(provider.histories[-1]) + estimate_tokens(provider.systems[-1]) < 16000
        assert runner.session.messages == before
    finally:
        runner.session.close()


def test_snapshot_is_bounded_valid_json():
    messages = [Message.user("old " * 5000), Message.user("new " * 5000)]
    body = snapshot(messages, plan="plan " * 10000, reply="reply " * 10000, limit=3000)
    assert len(body) <= 3000
    data = json.loads(body)
    assert "old" in data["earliest_retained_user_request_may_be_superseded"]
    assert "new" in data["latest_user_request"]
    assert "plan" in data["durable_plan_recorded_statuses"]
    assert "reply" in data["streaming_reply_incomplete"]


async def test_aside_only_reads_its_own_durable_plan(workdir):
    plans.update(workdir, "other session secret", [{"text": "unrelated"}], session_id="other")
    provider = Script([TextDelta("answer"), Done()])
    runner = build(workdir, provider)
    try:
        _ = [chunk async for chunk in runner.aside("hello")]
        assert "other session secret" not in provider.systems[-1]
        assert "durable_plan_recorded_statuses" not in context(provider)
    finally:
        runner.session.close()
