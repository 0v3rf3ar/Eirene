"""Durable project plans and verification criteria."""

from __future__ import annotations

import pytest

from eirene.core import paths, plans
from eirene.core.errors import ToolError


def test_plan_round_trip_and_render(workdir):
    rendered = plans.update(workdir, "Ship feature", [
        {"text": "Implement it", "status": "in_progress",
         "verification": "unit tests pass"},
        {"text": "Document it", "status": "pending"},
    ], "Keep compatibility")
    assert "Objective: Ship feature" in rendered
    assert "verify: unit tests pass" in rendered
    loaded = plans.load(workdir)
    assert loaded.steps[0].status == "in_progress"
    assert loaded.notes == "Keep compatibility"
    assert next(paths.plans_dir().glob("*.json")).stat().st_size > 0


def test_setting_in_progress_demotes_the_previous_step(workdir):
    plans.update(workdir, "Do work", [
        {"text": "One", "status": "in_progress"},
        {"text": "Two", "status": "pending"},
    ])
    plans.set_status(workdir, 2, "in_progress")
    statuses = [step.status for step in plans.load(workdir).steps]
    assert statuses == ["pending", "in_progress"]


def test_plan_rejects_multiple_active_steps(workdir):
    with pytest.raises(ToolError, match="only one"):
        plans.update(workdir, "Bad", [
            {"text": "One", "status": "in_progress"},
            {"text": "Two", "status": "in_progress"},
        ])


def test_plan_status_and_index_are_validated(workdir):
    plans.update(workdir, "Work", [{"text": "One"}])
    with pytest.raises(ToolError, match="does not exist"):
        plans.set_status(workdir, 2, "completed")
    with pytest.raises(ToolError, match="invalid"):
        plans.set_status(workdir, 1, "almost")


def test_plan_is_project_scoped(workdir, tmp_path):
    plans.update(workdir, "Mine", [{"text": "One"}])
    other = tmp_path / "other"
    other.mkdir()
    assert plans.load(other).active is False


def test_clear_removes_the_plan(workdir):
    plans.update(workdir, "Mine", [{"text": "One"}])
    assert plans.clear(workdir) == "plan cleared"
    assert plans.load(workdir).render() == "no active plan"
