"""/git"""

from __future__ import annotations

from rich.text import Text

from ..core import git as git_ops
from ..core.errors import CommandError, ToolError
from ..ui.chat import Block
from . import register


@register("git", "show changes, checkpoints, or restore one", "/git [status|diff|restore]")
async def run(app, args: str) -> None:
    action, _, value = args.strip().partition(" ")
    action = action.lower() or "status"
    if git_ops.repository(app.sandbox.root) is None:
        raise CommandError("this directory is not inside a Git repository")
    if action == "status":
        await _show(app, git_ops.status(app.sandbox.root))
        return
    if action == "diff":
        await _show(app, git_ops.diff(app.sandbox.root, value.strip()))
        return
    if action in ("checkpoints", "checkpoint"):
        await _show(app, git_ops.list_checkpoints(app.sandbox.root))
        return
    if action not in ("restore", "rollback"):
        raise CommandError("use /git status, diff, checkpoints or restore")
    checkpoint_id = value.strip()
    if not checkpoint_id:
        listed = git_ops.list_checkpoints(app.sandbox.root)
        rows = []
        for line in listed.splitlines():
            checkpoint = line.split(maxsplit=1)[0]
            if checkpoint and checkpoint != "no":
                rows.append((checkpoint, checkpoint, line[len(checkpoint):].strip()))
        if not rows:
            app.say("no checkpoints")
            return
        checkpoint_id = await app.ask_choice("restore which checkpoint?", rows) or ""
    if not checkpoint_id:
        return
    confirmed = await app.ask_choice(
        f"restore checkpoint {checkpoint_id}? current later changes will be replaced",
        [("yes", "restore it", "recover the earlier dirty tree"),
         ("no", "cancel", "keep current files")])
    if confirmed != "yes":
        app.say("cancelled")
        return
    try:
        note = git_ops.rollback(app.sandbox.root, checkpoint_id)
    except ToolError as exc:
        raise CommandError(exc.user_message()) from exc
    app.say(note)


async def _show(app, content: str) -> None:
    await app.push(Block(Text(content)))
