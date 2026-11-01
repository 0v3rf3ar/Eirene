"""Bubblewrap readiness: the /sandbox probe and the installer's warning."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from eirene.commands import dispatch
from eirene.tools import isolation

from test_release import installer  # noqa: F401 - the shared installer fixture
from test_tui import content, start

ROOT = Path(__file__).resolve().parents[1]
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Bubblewrap is Linux-only")


def fake_bwrap(monkeypatch, *, installed=True, returncode=0, stderr="", settings=None,
               container=False, managers=("apt-get",)):
    """Pretend about bwrap, the package manager and the kernel settings."""
    def which(name):
        if name == "bwrap":
            return "/usr/bin/bwrap" if installed else None
        return f"/usr/bin/{name}" if name in managers else None
    monkeypatch.setattr(isolation.shutil, "which", which)
    monkeypatch.setattr(isolation.os, "geteuid", lambda: 1000)
    runs = []

    def run(argv, **kwargs):
        runs.append(argv)
        return SimpleNamespace(returncode=returncode, stderr=stderr)
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(isolation, "_setting", lambda path: (settings or {}).get(Path(path).name, ""))
    monkeypatch.setattr(isolation, "_in_container", lambda: container)
    return runs


def test_a_working_bubblewrap_has_no_problem(monkeypatch):
    runs = fake_bwrap(monkeypatch)
    assert isolation.bubblewrap_problem() == ("", [])
    # The probe uses the same isolation as a real command.
    assert runs[0][:6] == ["/usr/bin/bwrap", "--die-with-parent", "--new-session",
                           "--unshare-all", "--cap-drop", "ALL"]


@pytest.mark.parametrize("managers, command", [
    (("apt-get",), "sudo apt install bubblewrap"),
    (("dnf", "yum"), "sudo dnf install bubblewrap"),
    (("pacman",), "sudo pacman -S bubblewrap"),
    (("apk",), "sudo apk add bubblewrap"),
])
def test_missing_bubblewrap_names_the_install_command(monkeypatch, managers, command):
    fake_bwrap(monkeypatch, installed=False, managers=managers)
    problem, fixes = isolation.bubblewrap_problem()
    assert problem == "Bubblewrap is not installed."
    assert fixes == [f"Install it: {command}"]


def test_missing_bubblewrap_without_a_known_package_manager(monkeypatch):
    fake_bwrap(monkeypatch, installed=False, managers=())
    assert isolation.bubblewrap_problem()[1] == ["Install your distribution's bubblewrap package."]


@pytest.mark.parametrize("settings, words, fix", [
    ({"unprivileged_userns_clone": "0"}, "turned off", "kernel.unprivileged_userns_clone=1"),
    ({"max_user_namespaces": "0"}, "turned off", "user.max_user_namespaces=15000"),
    ({"apparmor_restrict_unprivileged_userns": "1"}, "AppArmor", "kernel.apparmor_restrict_unprivileged_userns=0"),
])
def test_blocked_namespaces_name_the_setting_to_change(monkeypatch, settings, words, fix):
    fake_bwrap(monkeypatch, returncode=1, stderr="bwrap: setting up uid map: Permission denied\n",
               settings=settings)
    problem, fixes = isolation.bubblewrap_problem()
    assert words in problem and "setting up uid map: Permission denied" in problem
    assert f"sudo sysctl -w {fix}" in fixes[0]
    assert isolation.USERNS_SYSCTL_FILE in fixes[1]


def test_a_container_is_named_when_no_setting_explains_it(monkeypatch):
    fake_bwrap(monkeypatch, returncode=1, stderr="bwrap: Creating new namespace failed: "
               "Operation not permitted\n", container=True)
    problem, fixes = isolation.bubblewrap_problem()
    assert "container" in problem and "nesting=1" in fixes[0]


def test_an_unexplained_failure_still_shows_bwraps_reason(monkeypatch):
    fake_bwrap(monkeypatch, returncode=1, stderr="bwrap: something odd\n")
    assert isolation.bubblewrap_problem()[0] == "Bubblewrap failed: something odd"


@linux_only
async def test_sandbox_panel_shows_why_and_how_to_fix(workdir, monkeypatch):
    monkeypatch.setattr(isolation, "bubblewrap_problem", lambda: (
        "AppArmor blocks user namespaces (setting up uid map: Permission denied).",
        ["Allow now: sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0"]))
    app, pilot, context = await start(workdir, size=(120, 40))
    try:
        await dispatch(app, "/sandbox")
        await pilot.pause()
        body = content(app.aside.body)
        assert "Unavailable" in body
        assert "AppArmor blocks user namespaces" in body
        # The command fits on one line so it can be copied whole.
        assert "sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0" in body
        assert "No unsandboxed fallback." in body
    finally:
        await context.__aexit__(None, None, None)


@linux_only
async def test_sandbox_panel_says_ready_when_the_probe_passes(workdir, monkeypatch):
    monkeypatch.setattr(isolation, "bubblewrap_problem", lambda: ("", []))
    app, pilot, context = await start(workdir)
    try:
        await dispatch(app, "/sandbox")
        await pilot.pause()
        assert "Ready" in content(app.aside.body)
    finally:
        await context.__aexit__(None, None, None)


# The installer, run against a fake release with a PATH that hides or fakes bwrap.

@pytest.fixture
def sandboxed_installer(installer, tmp_path):
    run, env, _ = installer
    tools = Path(env["PATH"].split(os.pathsep)[0])
    # Every system tool except bwrap, so its absence can be simulated.
    system = tmp_path / "system"
    system.mkdir()
    for folder in os.environ["PATH"].split(os.pathsep):
        if not os.path.isdir(folder):
            continue
        for entry in os.listdir(folder):
            target = system / entry
            if entry != "bwrap" and not target.exists():
                target.symlink_to(os.path.join(folder, entry))
    path = f"{tools}{os.pathsep}{system}"

    def install(bwrap: str | None = None, **overrides):
        if bwrap is not None:
            (tools / "bwrap").write_text(bwrap)
            (tools / "bwrap").chmod(0o755)
        return run(PATH=path, **overrides)
    return install


@linux_only
def test_installer_warns_when_bubblewrap_is_missing(sandboxed_installer):
    result = sandboxed_installer()
    assert result.returncode == 0, result.stderr
    assert "warning: Command sandbox not ready: Bubblewrap is not installed" in result.stderr
    assert "install bubblewrap" in result.stderr or "-S bubblewrap" in result.stderr
    # The warning comes before the final message, not lost above it.
    assert "is installed." in result.stdout


@linux_only
def test_installer_explains_a_blocked_bubblewrap(sandboxed_installer):
    result = sandboxed_installer(
        "#!/bin/sh\necho 'bwrap: setting up uid map: Permission denied' >&2\nexit 1\n")
    assert result.returncode == 0, result.stderr
    assert "setting up uid map: Permission denied" in result.stderr
    assert "Command sandbox" in result.stderr


@linux_only
def test_installer_confirms_a_working_bubblewrap(sandboxed_installer):
    result = sandboxed_installer("#!/bin/sh\nexit 0\n")
    assert result.returncode == 0, result.stderr
    assert "[ok] Command sandbox ready" in result.stdout
    assert "warning" not in result.stderr


def test_installer_skips_the_bubblewrap_check_on_macos(installer):
    run, _, _ = installer
    result = run(TEST_OS="Darwin", TEST_CPU="arm64")
    assert result.returncode == 0, result.stderr
    assert "sandbox" not in (result.stdout + result.stderr).lower()
