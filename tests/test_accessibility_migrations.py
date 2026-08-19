"""Accessible rendering flags and persisted schema migrations."""

from __future__ import annotations

import json

from eirene.__main__ import main
from eirene.core import paths
from eirene.core.session import SCHEMA, Session, read_records
from eirene.scheduling.base import TASK_SCHEMA, Schedule, Task, load_tasks, save_tasks
from eirene.ui import art


def test_accessible_icons_are_ascii():
    art.set_accessible(True)
    try:
        assert art.icon("ok").isascii()
        assert art.tool_icon("write_file") == "W"
        assert art.file_icon("thing.py") == "F"
        assert art.banner(100).isascii()
    finally:
        art.set_accessible(False)


def test_default_icons_need_no_private_font_glyphs():
    art.set_accessible(False)
    values = list(art.ICONS.values()) + list(art.TOOL_ICONS.values())
    assert all(not (0xE000 <= ord(char) <= 0xF8FF)
               for value in values for char in value)


def test_reduce_motion_cli_sets_a_one_run_override(monkeypatch, workdir):
    from eirene import __main__ as cli
    import sys
    seen = {}
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "open_session",
                        lambda sandbox, resume: seen.setdefault("value", True) and 0)
    assert main(["--reduce-motion", "-C", str(workdir)]) == 0
    assert seen["value"] is True


def test_new_sessions_write_the_current_schema(workdir):
    session = Session.create(workdir)
    session.add_user("hello")
    session.close()
    assert next(read_records(session.path))["schema"] == SCHEMA


def test_tasks_write_versioned_schema_and_read_legacy_lists(workdir):
    task = Task("one", "one", "work", str(workdir), Schedule("hourly"))
    save_tasks([task])
    stored = json.loads(paths.tasks_file().read_text(encoding="utf-8"))
    assert stored["version"] == TASK_SCHEMA
    assert stored["tasks"][0]["id"] == "one"
    paths.tasks_file().write_text(json.dumps([task.to_dict()]), encoding="utf-8")
    assert load_tasks()[0].id == "one"
