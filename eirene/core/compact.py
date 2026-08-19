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
    session.replace_history(rebuilt, summary)
    return before, estimate_messages(rebuilt), summary


async def _summarise(provider, model: str, transcript: str) -> str:
    parts: list[str] = []
    async for event in provider.stream([Message.user(transcript)], model,
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
    return "\n".join(rows)[:120_000]


def _safe_tail(messages: list[dict]) -> list[Message]:
    """Keep recent turns without orphaning tool results."""
    tail = messages[-KEEP_TAIL:]
    while tail and tail[0].get("role") == "tool":
        tail = tail[1:]
    while tail and tail[-1].get("role") == "assistant" and tail[-1].get("tool_calls"):
        tail = tail[:-1]
    return [Message(m) for m in tail]
