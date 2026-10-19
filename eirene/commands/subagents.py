"""Browse the saved delegation tree for the current session."""
from __future__ import annotations

import asyncio

from ..core.errors import CommandError
from ..core.session import list_sessions
from . import register


def session_tree(current, sandbox):
    """Build workspace-local relationships, including older delegate tool results."""
    nodes = {item["id"]: item for item in list_sessions(limit=100000, sandbox=sandbox)}
    nodes.setdefault(current.id, dict(id=current.id, name=current.name or "Current session",
                                     parent_id="", agent="", status="saved", links=[]))
    legacy = [(node["id"], report) for node in nodes.values() for report in node.get("links", [])]
    for parent, report in legacy:
        child = nodes.get(report.get("session_id"))
        if child and not child["parent_id"]:
            child.update(parent_id=parent, agent=report.get("agent", ""),
                         status=report.get("status", "saved"))
    root = current.id
    seen = set()
    while root not in seen and nodes[root]["parent_id"] in nodes:
        seen.add(root)
        root = nodes[root]["parent_id"]
    rows = []
    seen.clear()

    children = {}
    for node in nodes.values():
        children.setdefault(node['parent_id'], []).append(node['id'])

    def visit(key, depth):
        if key in seen:
            return
        seen.add(key)
        rows.append((nodes[key], depth))
        for child in children.get(key, []):
            visit(child, depth + 1)
    visit(root, 0)
    return rows


@register("subagents", "browse the current session's subagent hierarchy",
          "/subagents [parent|root|SESSION_ID]")
async def run(app, args: str) -> None:
    rows = await asyncio.to_thread(session_tree, app.session, app.sandbox.root)
    nodes = {node["id"]: node for node, _ in rows}
    lines, choices = [], []
    for node, depth in rows:
        marker = " (current)" if node["id"] == app.session.id else ""
        label = ("  " * depth + ("└─ " if depth else "")
                 + (node["agent"] or node["name"]) + marker)
        detail = f"{node['status']} · {node['id']} · {node['name']}"
        lines.append(f"{label} [{node['status']}] — {node['id']}")
        choices.append((node["id"], label, detail))
    tree_popup = getattr(app, "ask_session_tree", None)
    if not tree_popup:
        app.say("Session hierarchy:\n" + "\n".join(lines))
    if args:
        if args == "root":
            chosen = rows[0][0]["id"]
        elif args == "parent":
            chosen = nodes[app.session.id]["parent_id"]
            if chosen not in nodes:
                app.say("this session has no saved parent")
                return
        elif args in nodes:
            chosen = args
        else:
            raise CommandError("use /subagents [parent|root|SESSION_ID]; choose a session in this hierarchy")
    elif tree_popup:
        turn = getattr(app, "turn", None)
        chosen = await tree_popup(rows, allow_switch=not (turn and not turn.done()))
    else:
        if len(rows) == 1:
            app.say("no saved subagents for this session; native CLI subagents may not expose separate Eirene sessions")
            return
        turn = getattr(app, "turn", None)
        if turn and not turn.done():
            app.say("hierarchy shown; wait for the active turn to finish before opening a session")
            return
        chosen = await app.ask_choice("open a session in this hierarchy", choices)
    if chosen:
        await app.switch_session(chosen)
