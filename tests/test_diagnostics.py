"""Runtime logs and installation diagnostics."""

from __future__ import annotations

import json
import os

import pytest

from eirene.__main__ import main
from eirene.core import paths
from eirene.core.config import CONFIG_VERSION, Config
from eirene.core.diagnostics import collect, render
from eirene.core import logging as runtime_logging


def test_diagnostics_are_read_only_and_hide_credentials(capsys):
    config = Config.load()
    config.provider = "chatgpt"
    config.set_provider("chatgpt", api_key="super-secret", model="gpt-test")
    report = collect(config)
    output = render(report, json_output=True)
    assert report["ok"] is True
    assert report["config_version"] == CONFIG_VERSION
    assert "super-secret" not in output
    assert report["providers"] == [{"name": "chatgpt", "has_key": True,
                                     "has_url": False, "model": "gpt-test"}]


def test_doctor_cli_supports_json(capsys):
    assert main(["--doctor", "--json"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True
    assert body["data_home"] == str(paths.home())


def test_unknown_provider_makes_diagnostics_fail():
    config = Config.load()
    config.provider = "mystery"
    report = collect(config)
    assert report["ok"] is False
    assert "unknown" in render(report).lower()


def test_runtime_log_is_structured_and_private():
    logger = runtime_logging.configure(Config.load())
    logger.warning("test.event", extra={"session_id": "abc"})
    for handler in logger.handlers:
        handler.flush()
    records = [json.loads(line) for line in
               paths.runtime_log().read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "test.event"
    assert records[-1]["session_id"] == "abc"
    if os.name != "nt":
        assert paths.runtime_log().stat().st_mode & 0o077 == 0
