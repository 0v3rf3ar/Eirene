"""Default data location and migration from older installations."""

from pathlib import Path

import pytest

from eirene.core import paths
from eirene.core.config import Config


@pytest.fixture
def user_home(tmp_path, monkeypatch):
    user = tmp_path / "user"
    user.mkdir()
    monkeypatch.setattr(Path, "home", lambda: user)
    monkeypatch.delenv(paths.ENV_HOME, raising=False)
    return user


def test_default_data_root(user_home):
    assert paths.home() == user_home / ".local/share/eirene"
    paths.ensure_tree()
    assert paths.sessions_dir().is_dir()
    config = Config.load()
    config.save()
    assert (user_home / ".local/share/eirene/config.json").is_file()


def test_existing_data_migrates_on_startup(user_home):
    legacy = user_home / ".local/eirene"
    (legacy / "sessions").mkdir(parents=True)
    (legacy / "config.json").write_text('{"provider": "ollama-local"}')
    (legacy / "sessions/saved.jsonl").write_text("saved conversation")
    paths.ensure_tree()
    paths.ensure_tree()
    assert Config.load().provider == "ollama-local"
    assert (paths.sessions_dir() / "saved.jsonl").read_text() == "saved conversation"
    assert not legacy.exists()


def test_existing_new_root_is_not_overwritten(user_home):
    legacy = user_home / ".local/eirene"
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text('{"provider": "anthropic"}')
    paths.home().mkdir(parents=True)
    paths.config_file().write_text('{"provider": "ollama-local"}')
    paths.ensure_tree()
    assert Config.load().provider == "ollama-local"
    assert (legacy / "config.json").is_file()


def test_override_does_not_migrate_default_data(user_home, monkeypatch):
    legacy = user_home / ".local/eirene"
    legacy.mkdir(parents=True)
    override = user_home / "custom-data"
    monkeypatch.setenv(paths.ENV_HOME, str(override))
    paths.ensure_tree()
    assert paths.home() == override
    assert paths.sessions_dir().is_dir()
    assert legacy.is_dir()
    assert not (user_home / ".local/share/eirene").exists()
