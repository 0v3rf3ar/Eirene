"""Keep one failing event handler from taking the whole interface down.

Textual treats any exception escaping a message handler as fatal: it stops that
widget's message loop and exits the application. For an interactive agent that
is the wrong trade. A bad paste or a failed link click should cost one action,
not the session. This module contains such errors at the dispatch boundary so
the widget keeps processing messages, while `ErrorBudget` still lets a real
crash loop end the program instead of spinning.

Only apps that define ``contain_error(error, where) -> bool`` opt in. Every
other Textual app (the trust prompt, the session picker) keeps stock behaviour.
The app decides what is recoverable; Eirene refuses until its own mount handler
starts, so a failure building the initial widget tree still ends the program.
"""

from __future__ import annotations

import time
from asyncio import CancelledError
from collections import deque

from textual.message_pump import MessagePump

# Errors raised again after a containment decision carry this marker, so the
# app's last-chance handler does not try to contain them a second time.
ESCALATED = "_eirene_escalated"

_installed = False


class ErrorBudget:
    """Allow a few contained errors; a burst within `window` seconds is a crash loop."""

    def __init__(self, limit: int = 6, window: float = 10.0, clock=time.monotonic):
        self.limit = limit
        self.window = window
        self._clock = clock
        self._times: deque[float] = deque()

    def spend(self) -> bool:
        """Record one error; False once the burst exceeds the budget."""
        now = self._clock()
        while self._times and now - self._times[0] > self.window:
            self._times.popleft()
        self._times.append(now)
        return len(self._times) <= self.limit


def mark_escalated(error: BaseException) -> BaseException:
    try:
        setattr(error, ESCALATED, True)
    except (AttributeError, TypeError):
        pass  # Exceptions with __slots__ simply fall back to the fatal path.
    return error


def escalated(error: BaseException) -> bool:
    return bool(getattr(error, ESCALATED, False))


def handler_name(pump: MessagePump, message) -> str:
    """Where a dispatch failed, for logs and crash reports."""
    owner = type(pump).__name__
    widget_id = getattr(pump, "id", None)
    if widget_id:
        owner = f"{owner}#{widget_id}"
    return f"{owner}.{getattr(message, 'handler_name', type(message).__name__)}"


def install() -> bool:
    """Wrap Textual's dispatch once per process. False if Textual changed shape."""
    global _installed
    if _installed:
        return True
    original = getattr(MessagePump, "_dispatch_message", None)
    if original is None:
        return False

    async def _dispatch_message(self: MessagePump, message) -> None:
        try:
            await original(self, message)
        except CancelledError:
            raise
        except Exception as error:
            if escalated(error):
                raise
            try:
                app = self.app
            except Exception:  # noqa: BLE001 - no active app: stock behaviour
                raise error from None
            contain = getattr(app, "contain_error", None)
            if contain is None or not contain(error, handler_name(self, message)):
                raise mark_escalated(error)

    _dispatch_message.__wrapped__ = original  # type: ignore[attr-defined]
    MessagePump._dispatch_message = _dispatch_message  # type: ignore[method-assign]
    _installed = True
    return True
