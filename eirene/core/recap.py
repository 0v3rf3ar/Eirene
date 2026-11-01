"""When to show a short session recap, and how to tidy the model's text.

A recap is display-only: it is never added to the conversation history, so it
cannot itself make the context grow.
"""

from __future__ import annotations

# A recap follows a completed turn once the transcript has grown by this many
# screen heights since the last one. Measuring what the user scrolls through
# counts tool cards, diffs and replies alike, for every provider, and adapts
# to the terminal size.
SCREENS = 2.0
MAX_CHARS = 400


class Tracker:
    """Remembers the transcript height at the last recap for one session."""

    def __init__(self) -> None:
        self.mark = 0

    def due(self, height: int, screen: int) -> bool:
        if height <= 0 or screen <= 0:
            return False
        if height < self.mark:
            # /clear or a fresh render shrank the transcript; start over here.
            self.mark = height
            return False
        return height - self.mark >= screen * SCREENS

    def shown(self, height: int) -> None:
        self.mark = height


def clean(text: str) -> str:
    """One line, no label or quotes; empty when unusable."""
    line = " ".join(text.split())
    for prefix in ("※", "recap:", "Recap:", "RECAP:"):
        line = line.strip().removeprefix(prefix)
    line = line.strip().strip('"“”').strip()
    if len(line) > MAX_CHARS or len(line.split()) < 5:
        return ""
    if not line.endswith((".", "!", "?", "。", "！", "？")):
        return ""
    return line
