"""Saved delegation navigation and transcript integration."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from eirene.commands.subagents import run, session_tree
from eirene.core.session import Session


def child_of(parent, label="reviewer"):
    child = Session.create(parent.sandbox)
    child.start()
    child.add_note("delegation", parent_id=parent.id, agent=label, status="running")
    child.add_user("Inspect errors")
    child.add_assistant("Found an issue", [{"id": "call", "name": "read_file", "arguments": {"path": "main.py"}}])
    child.add_tool_result("call", "read_file", "source code")
    child.add_note("delegation_status", status="completed")
    child.close()
    return child


def test_tree_survives_resume_and_filters_workspace(workdir, tmp_path):
    root = Session.create(workdir)
    root.add_user("Main task")
    child = child_of(root)
    grandchild = child_of(child, "nested")
    other = Session.create(tmp_path)
    other.add_user("Unrelated workspace")
    child_of(other)
    resumed = Session.resume(child.id)
    rows = session_tree(resumed, workdir)
    assert [(n["id"], d) for n, d in rows] == [(root.id, 0), (child.id, 1), (grandchild.id, 2)]
    assert rows[1][0]["status"] == "completed"
    assert any(m.get("name") == "read_file" for m in resumed.messages)
    for session in (root, other, resumed):
        session.close()


def test_legacy_tool_results_link_children(workdir):
    parent = Session.create(workdir)
    parent.add_user("Review")
    child = Session.create(workdir)
    child.add_user("Legacy review")
    child.close()
    parent.add_tool_result("call", "delegate_tasks", json.dumps([
        {"session_id": child.id, "agent": "reviewer", "status": "completed"}]))
    assert session_tree(child, workdir)[0][0]["id"] == parent.id
    parent.close()


async def test_picker_and_return_to_parent(workdir):
    parent = Session.create(workdir)
    parent.add_user("Task")
    child = child_of(parent)
    app = SimpleNamespace(session=parent, sandbox=SimpleNamespace(root=workdir),
                          say=lambda *a: None, ask_choice=AsyncMock(return_value=child.id),
                          switch_session=AsyncMock(), turn=None)
    await run(app, "")
    app.switch_session.assert_awaited_once_with(child.id)
    app.session = child
    await run(app, "parent")
    assert app.switch_session.await_args.args == (parent.id,)
    await run(app, "root")
    assert app.switch_session.await_args.args == (parent.id,)
    parent.close()


async def test_active_turn_lists_without_opening_picker(workdir):
    parent = Session.create(workdir)
    parent.add_user("Task")
    child_of(parent)
    app = SimpleNamespace(session=parent, sandbox=SimpleNamespace(root=workdir),
                          say=lambda *a: None, ask_choice=AsyncMock(), switch_session=AsyncMock(),
                          turn=SimpleNamespace(done=lambda: False))
    await run(app, "")
    app.ask_choice.assert_not_awaited()
    app.switch_session.assert_not_awaited()
    parent.close()
