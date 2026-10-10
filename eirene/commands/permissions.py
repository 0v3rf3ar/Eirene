"""Change execution access for the current Eirene process."""
from . import register
from ..core.errors import CommandError
from ..core.permissions import full_access


@register("permissions", "change execution restrictions",
          "/permissions [sandboxed|full-access]", wants_args=True)
async def run(app, args: str) -> None:
    wanted = args.strip().lower()
    if not wanted:
        current = app.config.get("permissions", "sandboxed")
        options = [
            ("sandboxed", "Sandboxed", "current" if current == "sandboxed" else "",
             "Workspace isolation and approval checks. Default for new processes."),
            ("full-access", "Full access", "current" if current == "full-access" else "",
             "Host files, network and commands without isolation. Approval follows the mode. "
             "OS privileges still apply. Lasts for this process; plan mode remains read-only."),
        ]
        wanted = await app.ask_choice("permissions", options, selected=current)
        if not wanted:
            return
    if wanted not in {"sandboxed", "full-access"}:
        raise CommandError("use /permissions sandboxed or /permissions full-access")
    if getattr(app, "turn", None) and not app.turn.done():
        raise CommandError("stop the current turn before changing permissions")
    if wanted == "sandboxed" and full_access(app.config):
        from ..tools import processes
        await processes.stop_all()
        await app.agent.mcp.close()
    app.config.set("permissions", wanted)
    app.sandbox.full_access = full_access(app.config)
    app.agent._tool_cache.clear()
    provider = app.agent.provider
    setter = getattr(provider, "set_permissions", None)
    if setter:
        setter(wanted)
    app.say(f"Permissions: {wanted}. " + (
        "Host files, network and commands are available; approval follows the mode. OS privileges still apply. "
        "Plan mode remains read-only."
        if full_access(app.config) else "Managed processes stopped; workspace isolation and approval checks are enabled."))
