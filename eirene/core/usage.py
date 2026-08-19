"""Session token accounting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class Turn:
    """Tokens and time for one exchange."""

    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    model: str = ""


@dataclass
class Usage:
    """Running totals for the session."""

    input_tokens: int = 0
    output_tokens: int = 0
    turns: list[Turn] = field(default_factory=list)
    started: float = field(default_factory=time.time)

    def record(self, input_tokens: int, output_tokens: int, seconds: float,
               model: str = "") -> None:
        self.input_tokens += max(input_tokens, 0)
        self.output_tokens += max(output_tokens, 0)
        self.turns.append(Turn(input_tokens, output_tokens, seconds, model))

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def elapsed(self) -> float:
        return time.time() - self.started

    def by_model(self) -> dict[str, tuple[int, int]]:
        out: dict[str, tuple[int, int]] = {}
        for turn in self.turns:
            name = turn.model or "unknown"
            got = out.get(name, (0, 0))
            out[name] = (got[0] + turn.input_tokens, got[1] + turn.output_tokens)
        return out

    def estimated_cost(self, prices: dict) -> float | None:
        """Configured USD estimate; None when any used model has no price."""
        if not self.turns:
            return 0.0
        total = 0.0
        for model, (input_tokens, output_tokens) in self.by_model().items():
            price = prices.get(model) if isinstance(prices, dict) else None
            if not isinstance(price, dict):
                return None
            try:
                input_rate = float(price.get("input_per_million", 0))
                output_rate = float(price.get("output_per_million", 0))
            except (TypeError, ValueError):
                return None
            total += input_tokens * input_rate / 1_000_000
            total += output_tokens * output_rate / 1_000_000
        return total


def estimate_tokens(text: str) -> int:
    """Rough count when the API gives none."""
    return max(1, len(text) // 4) if text else 0


def estimate_messages(messages: list[dict]) -> int:
    total = 0
    for message in messages:
        total += estimate_tokens(str(message.get("content") or ""))
        for call in message.get("tool_calls") or []:
            total += estimate_tokens(str(call.get("arguments") or ""))
    return total


def human_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes, rest = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {rest}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def human_count(value: int) -> str:
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1000:.1f}k".replace(".0k", "k")
    return f"{value / 1_000_000:.1f}M".replace(".0M", "M")
