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
    grouped = "ollama" if key == "ollama-local" else key
    assert rows[grouped] == "configured"
    assert "ollama-local" not in rows
    assert all(rows[other] == "" for other in KEYLESS if other not in {key, "ollama-local"})


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
    assert ("configured" in rows["ollama"]) is bool(model)
    if model:
        assert Config.load(config.path).provider == "ollama-local"


@pytest.mark.parametrize("key", ["ollama", "ollama-local"])
async def test_one_ollama_row_routes_to_existing_connections(config, key):
    config.provider = key
    config.set_provider(key, model="saved-model", api_key="saved-cloud-key" if key == "ollama" else "")
    choice = AsyncMock(side_effect=["ollama", key])
    app = SimpleNamespace(config=config, ask_choice=choice)
    assert await _pick(app, "") == key
    menu, connections = choice.call_args_list
    assert [row[1] for row in menu.args[1]].count("Ollama") == 1
    assert menu.kwargs["selected"] == "ollama"
    assert next(row[2] for row in menu.args[1] if row[0] == "ollama") == "configured, active"
    assert connections.kwargs["selected"] == key
    assert {row[0] for row in connections.args[1]} == {"ollama", "ollama-local"}
    assert config.provider == key


async def test_ollama_picker_cancellation_keeps_saved_connection(config):
    config.provider = "ollama-local"
    choice = AsyncMock(side_effect=["ollama", None])
    assert await _pick(SimpleNamespace(config=config, ask_choice=choice), "") == ""
    assert config.provider == "ollama-local"


async def test_ollama_cloud_alias_bypasses_group_but_ollama_opens_it(config):
    choice = AsyncMock(return_value="ollama-local")
    app = SimpleNamespace(config=config, ask_choice=choice)
    assert await _pick(app, "ollama-cloud") == "ollama"
    assert await _pick(app, "ollama-local") == "ollama-local"
    choice.assert_not_awaited()
    assert await _pick(app, "ollama") == "ollama-local"
    assert choice.call_args.args[0] == "Ollama connection"


@pytest.mark.parametrize("key", ["ollama", "ollama-local"])
async def test_grouped_ollama_setup_connects_and_keeps_other_settings(config, monkeypatch, key):
    other = "ollama-local" if key == "ollama" else "ollama"
    config.set_provider(other, model="other-saved-model")
    provider = SimpleNamespace(validate=AsyncMock(return_value="ok"),
                               models=AsyncMock(return_value=["chosen-model"]))
    builds = Mock(return_value=provider)
    monkeypatch.setattr("eirene.commands.connect.providers.build", builds)
    app = SimpleNamespace(config=config, say=Mock(),
                          ask_choice=AsyncMock(side_effect=["ollama", key, "chosen-model"]),
                          ask_text=AsyncMock(return_value="cloud-api-key"),
                          _save_config=config.save, agent=SimpleNamespace(use=Mock()),
                          refresh_mode_line=Mock())
    await run(app, "")
    assert config.provider == key
    assert config.model == "chosen-model"
    assert config.provider_config(other)["model"] == "other-saved-model"
    assert all(call.args[0] == key for call in builds.call_args_list)
    assert app.ask_text.await_count == (1 if key == "ollama" else 0)
    app.agent.use.assert_called_once_with(provider, key, "chosen-model")
