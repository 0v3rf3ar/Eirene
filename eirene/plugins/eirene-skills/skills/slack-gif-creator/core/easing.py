"""Easing curves: map linear progress t in [0, 1] to eased progress."""

from __future__ import annotations

import math
from typing import Callable


def linear(t: float) -> float:
    return t


def ease_in(t: float) -> float:
    return t * t * t


def ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def ease_in_out(t: float) -> float:
    return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def bounce_out(t: float) -> float:
    n, d = 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def bounce_in(t: float) -> float:
    return 1 - bounce_out(1 - t)


def elastic_out(t: float) -> float:
    if t in (0, 1):
        return t
    return 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * (2 * math.pi / 3)) + 1


def back_out(t: float, overshoot: float = 1.70158) -> float:
    c3 = overshoot + 1
    return 1 + c3 * (t - 1) ** 3 + overshoot * (t - 1) ** 2


def back_in(t: float, overshoot: float = 1.70158) -> float:
    return (overshoot + 1) * t ** 3 - overshoot * t * t


EASINGS: dict[str, Callable[[float], float]] = {
    "linear": linear,
    "ease_in": ease_in,
    "ease_out": ease_out,
    "ease_in_out": ease_in_out,
    "bounce_out": bounce_out,
    "bounce_in": bounce_in,
    "elastic_out": elastic_out,
    "back_out": back_out,
    "back_in": back_in,
}


def ease(t: float, easing: str = "linear") -> float:
    """Eased progress for t, clamped to [0, 1] on input."""
    try:
        curve = EASINGS[easing]
    except KeyError:
        raise ValueError(f"unknown easing {easing!r}; choose from {', '.join(EASINGS)}") from None
    return curve(min(1.0, max(0.0, t)))


def interpolate(start: float, end: float, t: float, easing: str = "linear") -> float:
    """Value between start and end at progress t with the named easing."""
    return start + (end - start) * ease(t, easing)


def progress(index: int, count: int) -> float:
    """Progress for frame index of count frames, from 0.0 to 1.0 inclusive."""
    return 0.0 if count <= 1 else index / (count - 1)


def ping_pong(t: float) -> float:
    """0 → 1 → 0 over t in [0, 1]; handy for loops that return to the start."""
    return 1 - abs(1 - 2 * (t % 1))
