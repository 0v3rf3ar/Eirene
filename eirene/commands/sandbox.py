"""Inspect the kernel-enforced execution sandbox."""
from . import register
from ..core.errors import CommandError
from rich.text import Text
from .usage import _styles, _append_box_line, _append_rule


@register("sandbox", "show kernel sandbox status", "/sandbox", wants_args=True)
async def run(app, args):
    if args.strip():
        raise CommandError("/sandbox shows status; platform isolation is automatic and has no container or image options")
    import shutil
    import sys
    if sys.platform == "darwin":
        runtime = "macOS / Seatbelt"
        available = bool(shutil.which("sandbox-exec"))
        notes = ["No unsandboxed fallback.", "Requires macOS sandbox-exec."]
    elif sys.platform == "win32":
        runtime = "Windows / native commands"
        available = False
        notes = ["No kernel command isolation.", "Native commands require individual approval.", "Plan mode uses portable file/search tools."]
    else:
        runtime = "Linux / Bubblewrap"
        available = bool(shutil.which("bwrap"))
        notes = ["No unsandboxed fallback.", "Requires Linux, bwrap, and permitted user namespaces."]
    external = getattr(app.agent.provider, "owns_context", False)
    styles = _styles(app)
    width = 64
    body = Text("╭─ sandbox " + "─" * (width - 10) + "─╮\n", style=styles["heading"])
    rows = [("Runtime", "External CLI" if external else runtime),
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
    notes = (["External CLI owns its sandbox.", "Eirene forwards its approval requests."] if external else notes)
    for note in notes:
        _append_box_line(body, note, width, styles, styles["muted"])
    body.append("╰" + "─" * width + "╯", style=styles["frame"])
    app.aside.show_content(body)
