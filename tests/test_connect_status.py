"""Connect status reflects completed setup rather than key requirements."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from eirene.commands.connect import _pick, run
from eirene.core.config import Config


KEYLESS = ["ollama-local", "claude-code", "chatgpt-subscription", "chatgpt-plan"]


async def test_fresh_connect_has_no_configured_providers(config):
    choice = AsyncMock(return_value=None)
    app = SimpleNamespace(config=config, ask_choice=choice)
    await _pick(app, "")
    await _pick(app, "")  # Reading credentials creates empty entries.
    rows = choice.call_args.args[1]
    assert all("configured" not in row[2] for row in rows)
    assert choice.call_args.kwargs["right_hint"] is True


@pytest.mark.parametrize("key", KEYLESS)
async def test_saved_keyless_connection_is_configured_after_reload(config, key):
    config.set_provider(key, model="saved-model")
    config.save()
    choice = AsyncMock(return_value=None)
    await _pick(SimpleNamespace(config=Config.load(config.path), ask_choice=choice), "")
    rows = {row[0]: row[2] for row in choice.call_args.args[1]}
    assert rows[key] == "configured"
    assert all(rows[other] == "" for other in KEYLESS if other != key)


@pytest.mark.parametrize("model", [None, "local-model"])
async def test_local_first_connection_status(config, monkeypatch, model):
    provider = SimpleNamespace(validate=AsyncMock(return_value="ok"),
                               models=AsyncMock(return_value=["local-model"]))
    monkeypatch.setattr("eirene.commands.connect.providers.build", lambda *a, **kw: provider)
    app = SimpleNamespace(config=config, say=Mock(), ask_choice=AsyncMock(return_value=model),
                          _save_config=config.save, agent=SimpleNamespace(use=Mock()),
                          refresh_mode_line=Mock())
    await run(app, "ollama-local")
    app.ask_choice = AsyncMock(return_value=None)
    await _pick(app, "")
    rows = {row[0]: row[2] for row in app.ask_choice.call_args.args[1]}
    assert ("configured" in rows["ollama-local"]) is bool(model)
    if model:
        assert Config.load(config.path).provider == "ollama-local"
