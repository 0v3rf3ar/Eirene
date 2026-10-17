"""Workspace trust must be explicit and precede interactive initialization."""

from types import SimpleNamespace

import pytest

from eirene.ui.picker import Picker
from eirene.ui.trust import TrustBackdrop, WorkspaceTrust, confirm_workspace_trust


@pytest.mark.parametrize("keys", [("down", "enter"), ("escape",), ("ctrl+c",), ("ctrl+d",)])
async def test_decline_and_cancellation_deny_trust(workdir, keys):
    app = WorkspaceTrust(workdir)
    async with app.run_test() as pilot:
        await pilot.pause()
        picker = app.query_one(Picker)
        assert picker.waiting
        assert picker.options[picker.index][0] == "trust"
        await pilot.press(*keys)
        await pilot.pause()
    assert app.return_value is False


async def test_explicit_trust_continues(workdir):
    app = WorkspaceTrust(workdir)
    async with app.run_test() as pilot:
        await pilot.pause()
        explanation = str(app.query_one("#trust-explanation").render())
        assert str(workdir) in explanation
        backdrop = app.query_one(TrustBackdrop)
        assert "▀" in str(backdrop.render())
        assert backdrop.styles.opacity == 0.12
        assert backdrop.styles.layer == "watermark"
        await pilot.press("enter")
        await pilot.pause()
    assert app.return_value is True


@pytest.mark.parametrize("result, expected", [(True, True), (False, False), (None, False)])
def test_only_true_result_is_trusted(workdir, monkeypatch, result, expected):
    monkeypatch.setattr(WorkspaceTrust, "run", lambda self: result)
    assert confirm_workspace_trust(workdir) is expected


@pytest.mark.parametrize("resume", ["", "saved-session-id"])
def test_decline_never_initializes_session_or_agent(workdir, monkeypatch, resume):
    from eirene import app

    seen = []
    monkeypatch.setattr("eirene.ui.trust.confirm_workspace_trust",
                        lambda path: seen.append(path) or False)

    def unexpected(*args, **kwargs):
        pytest.fail("session/agent initialization before workspace trust")

    monkeypatch.setattr(app, "Eirene", unexpected)
    assert app.run(workdir, resume) == 0
    assert seen == [workdir.resolve()]


@pytest.mark.parametrize("resume", ["", "saved-session-id"])
def test_trust_check_precedes_initialization_each_launch(
        workdir, monkeypatch, resume):
    from eirene import app

    seen = []

    def confirm(path):
        seen.append(("trust", path))
        return True

    def initialize(path, saved):
        seen.append(("initialize", path, saved))
        return SimpleNamespace(run=lambda: seen.append("run"),
                               session=SimpleNamespace(saved=False))

    monkeypatch.setattr("eirene.ui.trust.confirm_workspace_trust", confirm)
    monkeypatch.setattr(app, "Eirene", initialize)
    for _ in range(2):
        assert app.run(workdir, resume) == 0
    assert seen == [("trust", workdir.resolve()),
                    ("initialize", workdir.resolve(), resume), "run"] * 2


def test_accepted_path_is_remembered_across_launches(workdir, monkeypatch):
    from eirene.core.config import Config

    asked = []
    monkeypatch.setattr(WorkspaceTrust, "run", lambda self: asked.append(self.workspace) or True)
    assert confirm_workspace_trust(workdir)
    assert confirm_workspace_trust(workdir / ".." / workdir.name)
    assert asked == [workdir.resolve()]
    assert Config.load().get("trusted_workspaces") == [str(workdir.resolve())]


def test_trust_does_not_extend_to_other_paths(workdir, monkeypatch):
    asked = []
    monkeypatch.setattr(WorkspaceTrust, "run", lambda self: asked.append(self.workspace) or True)
    child = workdir / "child"
    child.mkdir()
    assert confirm_workspace_trust(workdir)
    assert confirm_workspace_trust(child)
    assert asked == [workdir.resolve(), child.resolve()]


@pytest.mark.parametrize("answer", [False, None])
def test_declined_path_is_not_remembered(workdir, monkeypatch, answer):
    from eirene.core.config import Config

    monkeypatch.setattr(WorkspaceTrust, "run", lambda self: answer)
    assert not confirm_workspace_trust(workdir)
    assert Config.load().get("trusted_workspaces") == []
    monkeypatch.setattr(WorkspaceTrust, "run", lambda self: True)
    assert confirm_workspace_trust(workdir)
