"""Sandbox containment."""

from __future__ import annotations

import os

import pytest

from eirene.core.errors import SandboxError
from eirene.tools.sandbox import Sandbox

skip_on_windows = pytest.mark.skipif(os.name == "nt", reason="posix only")


def test_relative_path_resolves(box, workdir):
    assert box.resolve("a/b.txt") == workdir / "a" / "b.txt"


def test_root_itself_allowed(box, workdir):
    assert box.resolve(".") == workdir


def test_parent_traversal_rejected(box):
    with pytest.raises(SandboxError):
        box.resolve("../secret.txt")


def test_deep_traversal_rejected(box):
    with pytest.raises(SandboxError):
        box.resolve("a/b/../../../../etc/passwd")


def test_absolute_outside_rejected(box, outside):
    with pytest.raises(SandboxError):
        box.resolve(str(outside / "secret.txt"))


def test_absolute_inside_allowed(box, workdir):
    assert box.resolve(str(workdir / "ok.txt")) == workdir / "ok.txt"


def test_home_shortcut_rejected(box):
    with pytest.raises(SandboxError):
        box.resolve("~/.ssh/id_rsa")


def test_empty_path_rejected(box):
    with pytest.raises(SandboxError):
        box.resolve("   ")


@skip_on_windows
def test_symlink_escape_rejected(box, workdir, outside):
    os.symlink(outside, workdir / "escape")
    with pytest.raises(SandboxError):
        box.resolve("escape/secret.txt")


@skip_on_windows
def test_symlink_inside_allowed(box, workdir):
    (workdir / "real").mkdir()
    os.symlink(workdir / "real", workdir / "link")
    assert box.resolve("link/file.txt") == workdir / "real" / "file.txt"


def test_unicode_path(box, workdir):
    assert box.resolve("проект/файл.txt") == workdir / "проект" / "файл.txt"


def test_contains_matches_resolve(box, outside):
    assert box.contains("inside.txt")
    assert not box.contains(str(outside))


def test_relative_display(box, workdir):
    (workdir / "x.txt").write_text("", encoding="utf-8")
    assert box.relative(workdir / "x.txt") == "x.txt"


def test_sandbox_root_is_resolved(tmp_path):
    nested = tmp_path / "a" / ".." / "a"
    (tmp_path / "a").mkdir()
    assert Sandbox(nested).root == (tmp_path / "a").resolve()


def test_an_approved_path_is_reachable_only_while_permitted(workdir, outside):
    from eirene.tools.sandbox import Sandbox

    box = Sandbox(workdir)
    target = outside / "report.txt"
    with pytest.raises(SandboxError):
        box.resolve(str(target))
    with box.permit(str(target)):
        assert box.resolve(str(target)) == target.resolve()
        with pytest.raises(SandboxError):
            box.resolve(str(outside / "other.txt"))
    with pytest.raises(SandboxError):
        box.resolve(str(target))


def test_permitting_a_directory_covers_what_is_inside_it(workdir, outside):
    from eirene.tools.sandbox import Sandbox

    box = Sandbox(workdir)
    with box.permit(str(outside)):
        assert box.resolve(str(outside / "nested" / "file.txt"))


def test_permitting_nothing_changes_nothing(workdir, outside):
    from eirene.tools.sandbox import Sandbox

    box = Sandbox(workdir)
    with box.permit("", None):
        with pytest.raises(SandboxError):
            box.resolve(str(outside / "x.txt"))


def test_a_failed_call_still_reseals_the_sandbox(workdir, outside):
    from eirene.tools.sandbox import Sandbox

    box = Sandbox(workdir)
    target = outside / "boom.txt"
    with pytest.raises(RuntimeError):
        with box.permit(str(target)):
            raise RuntimeError("tool blew up")
    assert not box.permitted(target.resolve())
