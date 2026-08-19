"""/sessions"""

from __future__ import annotations

import shlex

from ..core.errors import CommandError, SessionError
from ..core.session import export_session, import_session, search_sessions
from ..ui.sessions import options
from . import register


@register("sessions", "switch, search, export, or import sessions",
          "/sessions [search TEXT|export ID PATH|import PATH]")
async def run(app, args: str) -> None:
    try:
        words = shlex.split(args)
    except ValueError as exc:
        raise CommandError(str(exc)) from exc
    action = words[0].lower() if words else "search"
    try:
        if action == "export":
            if len(words) != 3:
                raise CommandError("use /sessions export <id> <path.md|path.json>")
            target = app.sandbox.check_write_target(words[2])
            format = "json" if target.suffix.lower() == ".json" else "markdown"
            export_session(words[1], target, format)
            app.say(f"exported session to {app.sandbox.relative(target)}")
            return
        if action == "import":
            if len(words) != 2:
                raise CommandError("use /sessions import <path.json>")
            source = app.sandbox.resolve(words[1])
            session = import_session(source, app.sandbox.root)
            app.say(f"imported as session {session.id}")
            return
        query = " ".join(words[1:] if action == "search" else words)
        found = search_sessions(query, sandbox=app.sandbox.root)
    except SessionError as exc:
        raise CommandError(exc.user_message()) from exc
    if not found:
        app.say("no matching sessions")
        return
    chosen = await app.ask_choice("switch to which session?", options(found))
    if chosen:
        await app.switch_session(chosen)
