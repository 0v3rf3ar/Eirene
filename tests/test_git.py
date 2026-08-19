"""Git-aware status, checkpoints, rollback, and guarded commits."""

from __future__ import annotations

import subprocess

import pytest

from eirene.core import git
from eirene.core.errors import ToolError


def run(root, *args):
    return subprocess.run(args, cwd=root, text=True, capture_output=True,
                          check=True).stdout.strip()


@pytest.fixture
def repo(workdir):
    run(workdir, "git", "init", "-q")
    run(workdir, "git", "config", "user.name", "Eirene Test")
    run(workdir, "git", "config", "user.email", "eirene@example.invalid")
    (workdir / "tracked.txt").write_text("original\n", encoding="utf-8")
    run(workdir, "git", "add", "tracked.txt")
    run(workdir, "git", "-c", "commit.gpgsign=false", "commit", "-qm", "initial")
    return workdir


def test_status_and_diff_include_working_changes(repo):
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    assert "tracked.txt" in git.status(repo)
    assert "-original" in git.diff(repo)
    assert "+changed" in git.diff(repo)


def test_diff_against_revision_includes_working_changes(repo):
    (repo / "tracked.txt").write_text("review this\n", encoding="utf-8")
    result = git.diff_against(repo, "HEAD")
    assert "-original" in result and "+review this" in result


def test_diff_against_rejects_unsafe_revision(repo):
    with pytest.raises(ToolError, match="invalid base revision"):
        git.diff_against(repo, "HEAD --output=/tmp/nope")


def test_checkpoint_rollback_preserves_preexisting_dirty_work(repo):
    (repo / "tracked.txt").write_text("user work\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("keep me\n", encoding="utf-8")
    checkpoint_id = git.checkpoint(repo, "before agent")

    (repo / "tracked.txt").write_text("agent edit\n", encoding="utf-8")
    (repo / "untracked.txt").write_text("agent overwrite\n", encoding="utf-8")
    (repo / "created.txt").write_text("agent file\n", encoding="utf-8")

    note = git.rollback(repo, checkpoint_id)
    assert checkpoint_id in note
    assert (repo / "tracked.txt").read_text() == "user work\n"
    assert (repo / "untracked.txt").read_text() == "keep me\n"
    assert not (repo / "created.txt").exists()


def test_commit_stages_only_named_paths(repo):
    (repo / "one.txt").write_text("one\n", encoding="utf-8")
    (repo / "two.txt").write_text("two\n", encoding="utf-8")
    git.commit(repo, "add one", ["one.txt"])
    assert run(repo, "git", "show", "--pretty=", "--name-only", "HEAD") == "one.txt"
    assert "two.txt" in git.changed_paths(repo)


def test_checkpoint_rejects_another_repository(repo, tmp_path):
    checkpoint_id = git.checkpoint(repo)
    other = tmp_path / "other"
    other.mkdir()
    run(other, "git", "init", "-q")
    with pytest.raises(ToolError, match="different repository"):
        git.rollback(other, checkpoint_id)


def test_path_escape_is_rejected(repo):
    with pytest.raises(ToolError, match="escapes"):
        git.commit(repo, "bad", ["../outside"])


def test_non_repository_is_reported(workdir):
    assert git.repository(workdir) is None
    assert git.status(workdir) == "not a Git repository"
    with pytest.raises(ToolError):
        git.checkpoint(workdir)


def test_worktree_is_created_and_removed_inside_repo(repo):
    note = git.create_worktree(repo, "worktrees/feature", "feature-test")
    assert "worktree" in note.lower()
    assert (repo / "worktrees" / "feature" / "tracked.txt").exists()
    assert "removed" in git.remove_worktree(repo, "worktrees/feature")
    assert not (repo / "worktrees" / "feature").exists()


def test_worktree_path_cannot_escape(repo):
    with pytest.raises(ToolError, match="escapes"):
        git.create_worktree(repo, "../feature", "feature-test")
