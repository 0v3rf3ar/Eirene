"""Toggle the uncommitted-changes side panel."""

from . import register
from ..core.errors import CommandError
from ..ui.diff_panel import DiffPanel, repository_problem


@register("diff", "toggle the side panel of uncommitted Git changes", "/diff [on|off]")
async def run(app, args: str) -> None:
    if args not in {"", "on", "off"}:
        raise CommandError("use /diff [on|off]")
    panel = app.query_one(DiffPanel)
    if args != "off" and not panel.open:
        problem = await repository_problem(app.sandbox.root)
        if problem:
            app.say(f"{problem} The diff panel needs a Git repository in "
                    f"{app.sandbox.root}.", "warn")
            return
    if args == "on":
        panel.show()
    elif args == "off":
        panel.hide()
    else:
        panel.toggle()
