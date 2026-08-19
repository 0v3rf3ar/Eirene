"""Spotting a question the user is meant to answer."""

from __future__ import annotations

import re

FENCE = re.compile(r"^\s*(?:```|~~~)")
ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)]|[a-zA-Z][.)])\s+(?P<text>\S.*)$")
MARKERS = re.compile(r"[*_`~]+")
LEAD = re.compile(r"^(?:option\s*\d*[:.\-]?\s*)", re.IGNORECASE)
MAX_OPTIONS = 6
MAX_OPTION_CHARS = 70


def _lines(text: str) -> list[str]:
    """Body lines, with fenced code taken out."""
    out, inside = [], False
    for line in (text or "").splitlines():
        if FENCE.match(line):
            inside = not inside
            continue
        if not inside:
            out.append(line)
    return out


def wants_an_answer(text: str) -> bool:
    """True when the reply stops and waits for the user."""
    lines = [line.strip() for line in _lines(text) if line.strip()]
    if not lines:
        return False
    tail = lines[-1]
    if tail.endswith("?"):
        return True
    if tail.endswith(":") and _asks(tail):
        return True
    for line in reversed(lines[-6:]):
        if ITEM.match(line):
            continue
        return line.endswith("?") or (line.endswith(":") and _asks(line))
    return False


def _asks(line: str) -> bool:
    lowered = line.lower()
    return any(word in lowered for word in (
        "which", "what", "confirm", "choose", "prefer", "pick", "decide",
        "want", "should i", "shall i", "let me know", "tell me", "options"))


def options_from(text: str) -> list[str]:
    """The choices offered after the question, if any."""
    lines = [line for line in _lines(text)]
    asked = -1
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or ITEM.match(line):
            continue
        if stripped.endswith("?") or (stripped.endswith(":") and _asks(stripped)):
            asked = index
    if asked < 0:
        return []
    found: list[str] = []
    for line in lines[asked + 1:]:
        match = ITEM.match(line)
        if match:
            found.append(_clean(match.group("text")))
        elif found and line.strip():
            break
    picked = [item for item in found if item][:MAX_OPTIONS]
    return picked if len(picked) >= 2 else []


def _clean(text: str) -> str:
    """One option, without markdown or trailing prose."""
    body = MARKERS.sub("", text).strip()
    trimmed = LEAD.sub("", body).strip()
    body = trimmed or body
    for separator in (" — ", " – ", ": ", " - "):
        if separator in body:
            head = body.split(separator, 1)[0].strip()
            if len(head) >= 3:
                body = head
                break
    body = body.rstrip(".;,")
    if len(body) > MAX_OPTION_CHARS:
        body = body[:MAX_OPTION_CHARS].rsplit(" ", 1)[0] + "…"
    return body


def question_from(text: str) -> str:
    """The question line itself, for the picker title."""
    lines = [line.strip() for line in _lines(text) if line.strip()]
    for line in reversed(lines):
        if ITEM.match(line):
            continue
        if line.endswith(("?", ":")):
            return MARKERS.sub("", line).rstrip(":").strip()
    return "what would you like?"
