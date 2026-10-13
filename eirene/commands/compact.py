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

    progress = await app.show_compaction() if hasattr(app, "show_compaction") else None
    if progress is not None:
        app.mark_busy(True)
    try:
        context, budget = await app.agent.compaction_budget()
        if budget <= 0:
            raise CommandError("instructions, tools and response allowance exceed the model context budget")
        before, after, summary = await do_compact(app.session, app.agent.provider,
            app.agent.model, target_tokens=app.agent.compaction_target(budget),
            context_tokens=context or None,
            on_progress=progress.set_stage if progress is not None else app.say)
    finally:
        if progress is not None:
            app.mark_busy(False)
            await progress.remove()
    saved = max(before - after, 0)
    app.say(f"{art.icon('ok')} context {human_count(before)} → {human_count(after)} "
            f"tokens (saved ~{human_count(saved)})")
    head = summary.strip().splitlines()[:3]
    if head:
        app.say(" ".join(head)[:200], "info")
