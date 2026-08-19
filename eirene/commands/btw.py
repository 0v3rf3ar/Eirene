"""/btw"""

from __future__ import annotations

from ..core.errors import CommandError
from . import register


@register("btw", "ask a side question, not saved in the session", "/btw <question>",
          wants_args=True)
async def run(app, args: str) -> None:
    question = args.strip()
    if not question:
        raise CommandError("give me something to ask, e.g. /btw what does chmod 755 do")
    if not app.agent.ready:
        raise CommandError("no provider yet - run /connect first")
    app.start_aside(question)
