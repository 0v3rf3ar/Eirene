"""First-class, read-only code review workflow."""

from __future__ import annotations

import asyncio
import re

from ..core.modes import Mode
from ..ui.chat import UserBlock
from . import register


@register("review", "review working-tree changes for concrete defects",
          "/review [base]")
async def run(app, args: str) -> None:
    if app.turn and not app.turn.done():
        app.say("finish or stop the current turn before reviewing", "warn")
        return
    if not any((root / ".git").exists() for root in
               (app.sandbox.root, *app.sandbox.root.parents)):
        app.say("code review requires a Git repository", "warn")
        return
    base = args.strip()
    if base and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/@{}^-]*", base):
        app.say("invalid Git base revision", "warn")
        return
    scope = f"against {base}" if base else "in staged and unstaged changes"
    request = f"Review changes {scope}"
    instruction = f"""Perform a strict read-only code review {scope}.
Use run_command to inspect git status --short and
{'git diff ' + base if base else 'git diff and git diff --cached'} first.
Inspect enough surrounding code and use find_references and language_diagnostics
where they can confirm an issue. Focus only on actionable bugs, regressions,
security problems, race conditions, data loss, and missing validation or tests.
Do not edit files. Report findings first, ordered by severity. Format each as:
SEVERITY path:line — short title
Then give concise evidence, impact, and a specific fix. If there are no findings,
say exactly "No findings" and mention any verification gap. End with a one-line
review summary. Do not praise the code or summarize the diff before findings."""
    await app.push(UserBlock(request))
    previous = app.agent.mode
    app.agent.mode = Mode.PLAN

    async def review() -> None:
        try:
            await app._run_turn(instruction, record_text=request)
        finally:
            app.agent.mode = previous
            app.refresh_mode_line()

    app.refresh_mode_line()
    app.turn = asyncio.create_task(review())
