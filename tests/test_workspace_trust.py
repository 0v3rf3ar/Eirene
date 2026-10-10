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
def test_acceptance_precedes_initialization_and_repeats_each_launch(
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
