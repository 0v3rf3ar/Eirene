"""/config opens the settings file and keeps the running app in step with it."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from eirene.commands import config as command
from eirene.core.config import Config


def found(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


def test_editor_preference_order(monkeypatch):
    monkeypatch.setattr(command, "IS_WINDOWS", False)
    monkeypatch.setattr(command, "IS_MAC", False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setattr(command.shutil, "which", found("code", "nvim", "vim", "nano"))
    assert command._resolve_editor("code --wait") == ["code", "--wait"]
    assert command._resolve_editor("missing-editor") == ["nvim"]
    monkeypatch.setattr(command.shutil, "which", found("vim", "nano"))
    assert command._resolve_editor("") == ["vim"]
    monkeypatch.setattr(command.shutil, "which", found("nano"))
    assert command._resolve_editor("") == ["nano"]
    monkeypatch.setattr(command, "IS_WINDOWS", True)
    monkeypatch.setattr(command.shutil, "which", found())
    assert command._resolve_editor("") == ["notepad"]


def test_windows_terminal_editors_are_not_detached(monkeypatch):
    monkeypatch.setattr(command, "IS_WINDOWS", True)
    assert not command._is_gui(["vim.exe"])
    assert not command._is_gui(["nvim.exe"])
    assert command._is_gui(["notepad"])
    # "vime.exe".rstrip(".exe") strips characters down to "vim"; only the suffix may go.
    assert command._is_gui(["vime.exe"])


def app_for(config, tmp_path):
    said = []

    @contextmanager
    def suspend():
        yield

    return SimpleNamespace(config=config, said=said, _save_config=config.save, suspend=suspend,
                           say=lambda text, *args: said.append(text))


async def test_edits_are_reloaded_after_a_terminal_editor(monkeypatch, config, tmp_path):
    config.set("editor", "vim")
    config.save()
    config.set("permissions", "full-access")  # Process-local; never read back from disk.
    def edit(argv, **kwargs):
        body = json.loads(config.path.read_text())
        body["theme"] = "edited-theme"
        config.path.write_text(json.dumps(body))
    monkeypatch.setattr(command.shutil, "which", found("vim"))
    monkeypatch.setattr(command.subprocess, "run", edit)
    app = app_for(config, tmp_path)
    await command.run(app, "")
    assert config.get("theme") == "edited-theme"
    assert config.get("permissions") == "full-access"
    assert "Reloaded" in app.said[-1]
    # A later save keeps the edit instead of writing stale settings over it.
    config.save()
    assert json.loads(config.path.read_text())["theme"] == "edited-theme"


async def test_invalid_json_keeps_the_running_settings(monkeypatch, config, tmp_path):
    config.set("editor", "vim")
    config.set("theme", "before")
    config.save()
    monkeypatch.setattr(command.shutil, "which", found("vim"))
    monkeypatch.setattr(command.subprocess, "run",
                        lambda argv, **kwargs: config.path.write_text('{"theme": "after",}'))
    app = app_for(config, tmp_path)
    await command.run(app, "")
    assert config.get("theme") == "before"
    assert "not valid JSON" in app.said[-1] and "not applied" in app.said[-1]


async def test_gui_editors_say_to_restart(monkeypatch, config, tmp_path):
    config.set("editor", "code")
    monkeypatch.setattr(command.shutil, "which", found("code"))
    launched = []
    monkeypatch.setattr(command, "_detached", launched.append)
    app = app_for(config, tmp_path)
    await command.run(app, "")
    assert launched and launched[0][0] == "code"
    assert "Restart Eirene" in app.said[-1]


def test_reload_rejects_non_objects(config):
    config.path.write_text("[1, 2]")
    assert "JSON object" in config.reload()
    assert isinstance(config.data, dict)


@pytest.fixture
def config(tmp_path):
    return Config.load(tmp_path / "config.json")
