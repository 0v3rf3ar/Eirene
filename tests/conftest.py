"""Shared fixtures."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eirene.core import paths  # noqa: E402
from eirene.core.config import Config  # noqa: E402
from eirene.tools.sandbox import Sandbox  # noqa: E402


@pytest.fixture(autouse=True)
def eirene_home(tmp_path, monkeypatch):
    """Redirect all app data to a temp dir."""
    home = tmp_path / "eirene-home"
    # Visual regression tests explicitly render true-colour output. Do not let
    # the developer's terminal preference silently disable those colours.
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv(paths.ENV_HOME, str(home))
    paths.ensure_tree()
    return home


@pytest.fixture
def workdir(tmp_path):
    root = tmp_path / "work"
    root.mkdir()
    return root


@pytest.fixture
def box(workdir):
    return Sandbox(workdir)


@pytest.fixture
def config():
    return Config.load()


@pytest.fixture
def python_command():
    """Build a shell command that runs the current Python on every platform."""
    def build(code: str) -> str:
        argv = [sys.executable, "-c", code]
        return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    return build


@pytest.fixture
def outside(tmp_path):
    """A directory next to the sandbox."""
    other = tmp_path / "outside"
    other.mkdir()
    (other / "secret.txt").write_text("do not read", encoding="utf-8")
    return other


skip_on_windows = pytest.mark.skipif(os.name == "nt", reason="posix only")


@pytest.fixture(autouse=True)
def skip_startup_animation(monkeypatch):
    """Keep ordinary UI tests immediate; splash tests opt into the real timer."""
    monkeypatch.setattr("eirene.ui.splash.SPLASH_SECONDS", 0)
