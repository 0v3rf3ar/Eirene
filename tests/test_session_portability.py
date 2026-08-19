"""Session search, Markdown/JSON export, and safe import."""

from __future__ import annotations

import json

import pytest

from eirene.core.errors import SessionError
from eirene.core.session import (Session, export_session, import_session,
                                 search_sessions)


def saved(workdir):
    session = Session.create(workdir)
    session.add_user("Investigate the moon parser")
    session.add_assistant("The parser is fixed")
    session.close()
    return session


def test_search_matches_content_and_returns_snippets(workdir):
    session = saved(workdir)
    found = search_sessions("parser", sandbox=workdir)
    assert [item["id"] for item in found] == [session.id]
    assert found[0]["snippets"]
    assert search_sessions("absent", sandbox=workdir) == []


def test_markdown_export(workdir, tmp_path):
    session = saved(workdir)
    target = tmp_path / "session.md"
    export_session(session.id, target)
    body = target.read_text(encoding="utf-8")
    assert "## User" in body and "## Eirene" in body
    assert "moon parser" in body


def test_json_export_can_be_imported_as_a_new_session(workdir, tmp_path):
    session = saved(workdir)
    target = tmp_path / "session.json"
    export_session(session.id, target, "json")
    imported = import_session(target, workdir)
    assert imported.id != session.id
    assert [message["content"] for message in Session.resume(imported.id).messages] == [
        "Investigate the moon parser", "The parser is fixed"]


def test_import_rejects_arbitrary_json(workdir, tmp_path):
    source = tmp_path / "bad.json"
    source.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(SessionError, match="not an Eirene"):
        import_session(source, workdir)


def test_export_rejects_an_unknown_format(workdir, tmp_path):
    session = saved(workdir)
    with pytest.raises(SessionError, match="format"):
        export_session(session.id, tmp_path / "x", "xml")
