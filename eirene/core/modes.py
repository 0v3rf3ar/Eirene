"""Permission policy per mode."""

from __future__ import annotations

from enum import Enum
from .text import terminal_icon

from ..tools.registry import EXEC, READ, WRITE

ALLOW = "allow"
ASK = "ask"
BLOCK = "block"


class Mode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"
    ACCEPT = "accept"
    PLAN = "plan"

    @classmethod
    def _missing_(cls, value):
        # Settings saved while this mode was called "tools".
        return cls.ACCEPT if value == "tools" else None

    @property
    def label(self) -> str:
        return f"{self.value} mode"

    @property
    def icon(self) -> str:
        glyph = {"auto": "⚡︎", "manual": "⏸", "plan": "☷", "accept": "»"}[self.value]
        return terminal_icon(glyph)

    @property
    def blurb(self) -> str:
        return {
            "auto": "acts without asking inside the sandbox",
            "manual": "asks before every write and command",
            "plan": "reads only; makes no changes",
            "accept": "runs tools freely; asks before any file change",
        }[self.value]


CYCLE = [Mode.MANUAL, Mode.ACCEPT, Mode.AUTO, Mode.PLAN]

POLICY: dict[Mode, dict[str, str]] = {
    Mode.AUTO: {READ: ALLOW, WRITE: ALLOW, EXEC: ALLOW},
    Mode.MANUAL: {READ: ASK, WRITE: ASK, EXEC: ASK},
    Mode.PLAN: {READ: ALLOW, WRITE: BLOCK, EXEC: BLOCK},
    # Commands are allowed here, but the agent asks for any that can change files.
    Mode.ACCEPT: {READ: ALLOW, WRITE: ASK, EXEC: ALLOW},
}


def parse(value: str | None) -> Mode:
    text = (value or "manual").strip().lower()
    if text in {"tools", "accept-tools", "accept_tools", "acc"}:
        return Mode.ACCEPT
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
