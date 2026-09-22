"""Inspect the kernel-enforced execution sandbox."""
from . import register
from ..core.errors import CommandError
from rich.text import Text
from .usage import _styles, _append_box_line, _append_rule


@register("sandbox", "show kernel sandbox status", "/sandbox", wants_args=True)
async def run(app, args):
    if args.strip():
        raise CommandError("/sandbox shows status; Bubblewrap is automatic and has no container or image options")
    import shutil
    import sys
    available = sys.platform == "linux" and bool(shutil.which("bwrap"))
    external = getattr(app.agent.provider, "owns_context", False)
    styles = _styles(app)
    width = 64
    body = Text("╭─ sandbox " + "─" * (width - 10) + "─╮\n", style=styles["heading"])
    rows = [("Runtime", "External CLI" if external else "Linux / Bubblewrap"),
            ("Status", "Managed by provider" if external else "Installed" if available else "Unavailable"),
            ("Workspace", str(app.sandbox.root)),
            ("Edits", "Applied directly to your project"),
            ("External paths", "Explicit approval required"),
            ("Network", "Explicit approval required" if app.config.get("isolate_network", True) else "Enabled in configuration")]
    for label, value in rows:
        line = Text(f"{label:<16}", style=styles["muted"])
        line.append(value, style=styles["value"])
        line.truncate(width - 2, overflow="ellipsis")
        _append_box_line(body, line, width, styles)
    _append_rule(body, width, styles)
    notes = (["External CLI owns its sandbox.", "Eirene forwards its approval requests."] if external else
             ["No unsandboxed fallback.", "Requires Linux, bwrap, and permitted user namespaces."])
    for note in notes:
        _append_box_line(body, note, width, styles, styles["muted"])
    body.append("╰" + "─" * width + "╯", style=styles["frame"])
    app.aside.show_content(body)
