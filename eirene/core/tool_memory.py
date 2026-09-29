"""Bounded, factual execution memory independent of model summaries."""

from __future__ import annotations

import hashlib
import json


def fingerprint(name: str, arguments: dict) -> str:
    payload = json.dumps([name, arguments], sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    marker = "\n[… omitted …]\n"
    if limit <= len(marker):
        return text[:max(0, limit)]
    room = max(0, limit - len(marker))
    return text[:room // 2] + marker + text[-(room - room // 2):]


def execution_memory(messages: list[dict], limit: int = 2400) -> str:
    """Retain tool observations, not an assistant's claim of completion."""
    previous = next((str(m.get("execution_memory", "")) for m in messages
                     if m.get("execution_memory")), "")
    rows = previous.splitlines() if previous else []
    calls = {}
    for message in messages:
        for call in message.get("tool_calls") or []:
            calls[call["id"]] = call
        if message.get("role") != "tool":
            continue
        call = calls.pop(message.get("tool_call_id"), {})
        name = message.get("name", call.get("name", "tool"))
        args = call.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        target = args.get("path") or args.get("command") or args.get("process_id") or args.get("pattern") or ""
        state = "FAILED / inspect before retry" if message.get("is_error") else "RETURNED"
        result = " ".join(str(message.get("content") or "").split())
        artifact = message.get("artifact_id", "")
        row = f"{state}: {name} {shorten(str(target), 120)} => {shorten(result, 220)}"
        if artifact:
            row += f" [artifact {artifact}]"
        if row not in rows:
            rows.append(row)
    # Recent observations supersede older state; the full log remains on disk.
    kept = []
    size = 0
    for row in reversed(rows):
        if size + len(row) + 1 > limit:
            break
        kept.append(row)
        size += len(row) + 1
    return "\n".join(reversed(kept))


def compact_output(text: str, limit: int, artifact_id: str, *,
                   prefix_only: bool = False, source_required: bool = False) -> str:
    """Keep useful evidence and a retrieval recipe inside a strict character cap."""
    limit = max(0, limit)
    if len(text) <= limit and not source_required:
        return text
    source = (f"\n[output artifact: {artifact_id}; partial output. "
              "Use read_output with offset=0, limit=1024; follow next_offset.]")
    if limit < len(source):
        return "[Output saved; compact context before retrieving details.]"[:limit]
    room = limit - len(source)
    if prefix_only:
        body = text[:room]
        # Prefer complete rows; don't throw away an oversized single line.
        boundary = body.rfind("\n")
        if boundary >= room // 2:
            body = body[:boundary]
    else:
        body = shorten(text, room)
    return body + source
