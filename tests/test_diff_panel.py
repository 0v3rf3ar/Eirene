"""The /diff side panel."""

from __future__ import annotations

import asyncio
import shutil
import subprocess

import pytest

from eirene.ui import diff_panel
from eirene.ui.diff_panel import DiffPanel, FileSection

from test_tui import start, type_line

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def repo(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    (root / "README.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    (root / "app.py").write_text('__version__ = "0.1.0"\n', encoding="utf-8")
    git(root, "add", ".")
    git(root, "commit", "-qm", "init")
    (root / "README.md").write_text("one\ntwo\nthree\n\n## Valid\n", encoding="utf-8")
    (root / "app.py").write_text('__version__ = "0.2.0"\n', encoding="utf-8")
    (root / "TODO.md").write_text("later\n", encoding="utf-8")


def test_collects_changes_and_untracked(workdir):
    repo(workdir)
    snapshot = asyncio.run(diff_panel.collect(workdir))
    by_path = {item.path: item for item in snapshot.files}
    assert set(by_path) == {"README.md", "app.py", "TODO.md"}
    assert (by_path["README.md"].added, by_path["README.md"].removed) == (2, 0)
    assert (by_path["app.py"].added, by_path["app.py"].removed) == (1, 1)
    assert by_path["TODO.md"].untracked
    assert (snapshot.added, snapshot.removed) == (3, 1)


def test_repository_without_commits(workdir):
    git(workdir, "init", "-q")
    (workdir / "new.txt").write_text("x\n", encoding="utf-8")
    git(workdir, "add", "new.txt")
    snapshot = asyncio.run(diff_panel.collect(workdir))
    assert [(f.path, f.added) for f in snapshot.files] == [("new.txt", 1)]


def test_outside_a_repository(workdir):
    snapshot = asyncio.run(diff_panel.collect(workdir))
    assert snapshot.error == "No Git repository found." and not snapshot.files


async def test_diff_command_says_when_there_is_no_repository(workdir):
    app, pilot, context = await start(workdir, size=(140, 40))
    try:
        await type_line(pilot, "/diff")
        await pilot.pause(0.2)
        assert not app.query_one(DiffPanel).open
        notices = [str(getattr(block, "_Static__content", "")) for block in app.transcript.children]
        assert any("No Git repository found" in note for note in notices), notices
    finally:
        await context.__aexit__(None, None, None)


async def test_diff_command_toggles_the_panel(workdir):
    repo(workdir)
    app, pilot, context = await start(workdir, size=(140, 40))
    try:
        panel = app.query_one(DiffPanel)
        assert not panel.open
        await type_line(pilot, "/diff")
        for _ in range(50):
            await pilot.pause(0.05)
            if app.query(FileSection):
                break
        assert panel.open
        assert len(app.query(FileSection)) == 3
        await type_line(pilot, "/diff")
        assert not panel.open
    finally:
        await context.__aexit__(None, None, None)


async def test_narrow_window_takes_turns_between_chat_and_diff(workdir):
    from eirene.ui.chat import Transcript
    from eirene.ui.diff_panel import DiffToggle
    repo(workdir)
    app, pilot, context = await start(workdir, size=(80, 30))
    try:
        panel = app.query_one(DiffPanel)
        toggle = app.query_one(DiffToggle)
        before = len(app.transcript.children)
        await type_line(pilot, "/diff")
        await pilot.pause(0.1)
        assert len(app.transcript.children) == before
        # Open, but the chat keeps the whole narrow window until asked.
        assert panel.open and not panel.display
        assert toggle.display and app.query_one(Transcript).region.width == 80
        assert toggle.region.right == 79 and toggle.region.y == 0
        await pilot.click(DiffToggle)
        for _ in range(50):
            await pilot.pause(0.05)
            if app.query(FileSection):
                break
        assert panel.display and panel.region.width == 80
        assert len(app.query(FileSection)) == 3
        assert "chat" in str(toggle.render())
        await pilot.click(DiffToggle)
        await pilot.pause(0.1)
        assert panel.open and not panel.display
        assert app.query_one(Transcript).region.width == 80
        await type_line(pilot, "/diff")
        await pilot.pause(0.1)
        assert not panel.open and not toggle.display
    finally:
        await context.__aexit__(None, None, None)


async def test_panel_follows_the_window_width(workdir):
    from eirene.ui.diff_panel import DiffToggle
    repo(workdir)
    app, pilot, context = await start(workdir, size=(140, 40))
    try:
        panel = app.query_one(DiffPanel)
        toggle = app.query_one(DiffToggle)
        await type_line(pilot, "/diff")
        await pilot.pause(0.1)
        assert panel.display and not toggle.display
        await pilot.resize_terminal(70, 30)
        await pilot.pause(0.1)
        assert panel.open and not panel.display and toggle.display
        assert toggle.region.right == 69
        await pilot.resize_terminal(140, 40)
        await pilot.pause(0.1)
        assert panel.display and not panel.has_class("full") and not toggle.display
    finally:
        await context.__aexit__(None, None, None)
