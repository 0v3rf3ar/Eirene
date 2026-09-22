"""History compaction."""

from __future__ import annotations

from ..providers.base import TextDelta
from .errors import ProviderError
from .prompt import COMPACT_PROMPT
from .session import Message, Session
from .usage import estimate_messages

KEEP_TAIL = 4


async def compact(session: Session, provider, model: str) -> tuple[int, int, str]:
    """Summarise history; returns before, after, summary."""
    if len(session.messages) < 3:
        raise ProviderError("nothing to compact yet")
    before = estimate_messages(session.messages)
    transcript = _transcript(session.messages)
    summary = await _summarise(provider, model, transcript)
    if not summary:
        raise ProviderError("the model returned an empty summary")

    tail = _safe_tail(session.messages)
    rebuilt = [Message.user(f"Summary of the conversation so far:\n{summary}"),
               Message.assistant("Understood, continuing from there.")]
    rebuilt.extend(tail)
    if estimate_messages(rebuilt) >= before:
        # A complete recent tool group can be large. Keep it paired while
        # shortening only its result bodies; originals remain in the JSONL log.
        for message in rebuilt[2:]:
            if message.get("role") == "tool" and len(str(message.get("content", ""))) > 4000:
                body = str(message["content"])
                message["content"] = body[:2000] + "\n[older tool output shortened; see saved transcript/artifact]\n" + body[-2000:]
    session.replace_history(rebuilt, summary)
    return before, estimate_messages(rebuilt), summary


async def _summarise(provider, model: str, transcript: str) -> str:
    parts: list[str] = []
    stream = getattr(provider, "isolated_stream", provider.stream)
    async for event in stream([Message.user(transcript)], model,
                                       system=COMPACT_PROMPT, tools=None,
                                       max_tokens=2048):
        if isinstance(event, TextDelta):
            parts.append(event.text)
    return "".join(parts).strip()


def _transcript(messages: list[dict]) -> str:
    rows = []
    for message in messages:
        role = message.get("role")
        content = str(message.get("content") or "").strip()
        if role == "user":
            rows.append(f"USER: {content}")
        elif role == "assistant":
            if content:
                rows.append(f"ASSISTANT: {content}")
            for call in message.get("tool_calls") or []:
                rows.append(f"TOOL CALL: {call.get('name')} {call.get('arguments')}")
        elif role == "tool":
            flag = "ERROR" if message.get("is_error") else "RESULT"
            rows.append(f"{flag}: {content[:600]}")
    text = "\n".join(rows)
    if len(text) > 120_000:
        return text[:20_000] + "\n[older middle omitted; recent context follows]\n" + text[-100_000:]
    return text


def _safe_tail(messages: list[dict]) -> list[Message]:
    """Keep recent turns without orphaning tool results."""
    start = max(0, len(messages) - KEEP_TAIL)
    while start > 0 and messages[start].get("role") == "tool":
        start -= 1
    tail = messages[start:]
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    while tail and tail[-1].get("role") == "assistant" and tail[-1].get("tool_calls"):
        tail = tail[:-1]
    return [Message(m) for m in tail]
