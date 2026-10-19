"""Read-only, bounded context for side questions during a running session."""

from __future__ import annotations

import json
from collections.abc import Sequence

from .tool_memory import execution_memory, shorten


def snapshot(messages: list[dict], *, plan: str = "", activity: str = "",
             reply: str = "", queued: Sequence[str] = (), limit: int = 20000) -> str:
    """Keep task anchors even when tool exchanges have filled the recent tail.

    These are observations at request time, not a second agent's instructions or
    an inferred completion status. Original protocol messages remain untouched.
    """
    requests = [str(m.get("content") or "") for m in messages
                if m.get("role") == "user" and not m.get("host_generated")
                and not m.get("compaction_summary")]
    summary = next((str(m.get("content") or "") for m in reversed(messages)
                    if m.get("compaction_summary")), "")
    updates = [str(m["content"]) for m in messages
               if m.get("role") == "assistant" and m.get("content")
               and not m.get("host_generated") and not m.get("execution_memory")]
    pending = {}
    for message in messages:
        if message.get("role") == "assistant":
            pending.update({c["id"]: c for c in message.get("tool_calls") or []})
        elif message.get("role") == "tool":
            pending.pop(message.get("tool_call_id"), None)
    fields = {
        "latest_user_request": shorten(requests[-1], 2000) if requests else "",
        "durable_plan_recorded_statuses": shorten(plan, 4000),
        "main_turn_activity": activity or "No main turn is running in this agent.",
        "streaming_reply_incomplete": shorten(reply, 2000),
        "tool_calls_without_recorded_results": shorten(json.dumps(
            list(pending.values()), ensure_ascii=False), 2000) if pending else "",
        "queued_user_input_not_yet_consumed": shorten("\n".join(queued), 1200),
        "earliest_retained_user_request_may_be_superseded": shorten(requests[0], 1000) if requests else "",
        "compaction_handoff_may_be_outdated": shorten(summary, 3500),
        "recent_user_requests_oldest_first": "\n".join(shorten(r, 600) for r in requests[-8:-1]),
        "assistant_updates_may_be_outdated_not_verified": "\n".join(shorten(r, 600) for r in updates[-6:]),
        "recent_tool_observations_not_proof_of_completion": execution_memory(messages, 3500),
    }
    fields = {key: value for key, value in fields.items() if value}
    # Shrink values, never signed messages or JSON syntax. A small model context
    # still gets each source, rather than silently losing the middle of a plan.
    while len(body := json.dumps(fields, ensure_ascii=False)) > limit:
        key = max(fields, key=lambda k: len(fields[k]))
        size = len(fields[key])
        if size <= 32:
            break
        fields[key] = shorten(fields[key], max(32, size // 2))
    return body
