"""/compact"""

from __future__ import annotations

from ..core.compact import compact as do_compact
from ..core.errors import CommandError
from ..core.usage import human_count
from ..ui import art
from . import register


@register("compact", "summarise the chat so it costs fewer tokens")
async def run(app, args: str) -> None:
    if not app.agent.ready:
        raise CommandError("no provider yet - run /connect first")
    if app.turn and not app.turn.done():
        raise CommandError("wait for the current answer to finish")

    app.say("compacting…")
    before, after, summary = await do_compact(app.session, app.agent.provider,
                                              app.agent.model)
    saved = max(before - after, 0)
    app.say(f"{art.icon('ok')} context {human_count(before)} → {human_count(after)} "
            f"tokens (saved ~{human_count(saved)})")
    head = summary.strip().splitlines()[:3]
    if head:
        app.say(" ".join(head)[:200], "info")
