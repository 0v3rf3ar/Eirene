"""Environment, file, and optional OS credential storage."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from eirene.core.config import Config


class FakeKeyring:
    values = {}
    @classmethod
    def set_password(cls, service, name, value): cls.values[(service, name)] = value
    @classmethod
    def get_password(cls, service, name): return cls.values.get((service, name))
    @classmethod
    def delete_password(cls, service, name): cls.values.pop((service, name), None)
    @staticmethod
    def get_keyring(): return SimpleNamespace(priority=1)


def test_keyring_mode_does_not_persist_the_secret(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyring", FakeKeyring)
    config = Config.load()
    config.set("credential_store", "keyring")
    config.set_provider("chatgpt", api_key="secret")
    entry = config.provider_config("chatgpt")
    assert "api_key" not in entry and entry["api_key_ref"] == "keyring"
    assert config.api_key("chatgpt") == "secret"
    assert config.forget_provider("chatgpt")
    assert FakeKeyring.values == {}
