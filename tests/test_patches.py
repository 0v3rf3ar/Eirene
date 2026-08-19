"""Atomic multi-file unified patch application."""

from __future__ import annotations

import pytest

from eirene.core.errors import ToolError
from eirene.tools.patches import apply


def test_patch_updates_creates_and_deletes_files(workdir, box):
    (workdir / "old.txt").write_text("one\ntwo\n", encoding="utf-8")
    (workdir / "gone.txt").write_text("bye\n", encoding="utf-8")
    patch = """--- a/old.txt
+++ b/old.txt
@@ -1,2 +1,2 @@
 one
-two
+changed
--- /dev/null
+++ b/new.txt
@@ -0,0 +1,1 @@
+new
--- a/gone.txt
+++ /dev/null
@@ -1,1 +0,0 @@
-bye
"""
    note = apply(box, patch)
    assert "patched old.txt" in note and "deleted gone.txt" in note
    assert (workdir / "old.txt").read_text() == "one\nchanged\n"
    assert (workdir / "new.txt").read_text() == "new\n"
    assert not (workdir / "gone.txt").exists()


def test_all_hunks_are_validated_before_any_write(workdir, box):
    (workdir / "one.txt").write_text("one\n", encoding="utf-8")
    (workdir / "two.txt").write_text("two\n", encoding="utf-8")
    patch = """--- a/one.txt
+++ b/one.txt
@@ -1 +1 @@
-one
+changed
--- a/two.txt
+++ b/two.txt
@@ -1 +1 @@
-does not match
+bad
"""
    with pytest.raises(ToolError, match="does not match"):
        apply(box, patch)
    assert (workdir / "one.txt").read_text() == "one\n"


def test_patch_path_cannot_escape(box):
    patch = """--- /dev/null
+++ b/../outside.txt
@@ -0,0 +1 @@
+bad
"""
    with pytest.raises(ToolError):
        apply(box, patch)


def test_malformed_patch_is_rejected(box):
    with pytest.raises(ToolError, match="no file changes"):
        apply(box, "not a patch")
