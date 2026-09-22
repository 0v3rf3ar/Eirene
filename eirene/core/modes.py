"""Permission policy per mode."""

from __future__ import annotations

from enum import Enum

from ..tools.registry import EXEC, READ, WRITE

ALLOW = "allow"
ASK = "ask"
BLOCK = "block"


class Mode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    PLAN = "plan"

    @property
    def label(self) -> str:
        return f"{self.value} mode"

    @property
    def icon(self) -> str:
        return {"auto": "⚡︎", "manual": "⏸", "plan": "☷"}[self.value]

    @property
    def blurb(self) -> str:
        return {
            "auto": "acts without asking inside the sandbox",
            "manual": "asks before every write and command",
            "plan": "reads only; makes no changes",
        }[self.value]


CYCLE = [Mode.MANUAL, Mode.AUTO, Mode.PLAN]

POLICY: dict[Mode, dict[str, str]] = {
    Mode.AUTO: {READ: ALLOW, WRITE: ALLOW, EXEC: ALLOW},
    Mode.MANUAL: {READ: ASK, WRITE: ASK, EXEC: ASK},
    Mode.PLAN: {READ: ALLOW, WRITE: BLOCK, EXEC: BLOCK},
}


def parse(value: str | None) -> Mode:
    text = (value or "manual").strip().lower()
    for mode in Mode:
        if mode.value == text or mode.value.startswith(text):
            return mode
    return Mode.MANUAL


def next_mode(current: Mode) -> Mode:
    return CYCLE[(CYCLE.index(current) + 1) % len(CYCLE)]


def decide(mode: Mode, kind: str, escape: str = "") -> tuple[str, str]:
    """Return (decision, reason) for one tool call."""
    verdict = POLICY[mode].get(kind, ASK)
    if mode is Mode.PLAN:
        if verdict == BLOCK:
            return BLOCK, "plan mode makes no changes"
        if escape:
            return ASK, escape
        return ALLOW, ""
    if escape:
        # Leaving the sandbox is worth one question, not a dead end.
        return ASK, escape
    return verdict, ""


def auto_read_only(mode: Mode) -> bool:
    """True when reads never prompt."""
    return POLICY[mode].get(READ) == ALLOW
