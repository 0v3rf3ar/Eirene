"""Persistent config at ~/.local/eirene/config.json."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .errors import ConfigError
from . import paths

CONFIG_VERSION = 2

DEFAULTS: dict[str, Any] = {
    "version": CONFIG_VERSION,
    "provider": None,
    "model": None,
    "mode": "manual",
    "theme": "default",
    "providers": {},
    "skills": {},
    "shell_timeout": 120,
    "max_iterations": 0,
    "max_output_bytes": 200_000,
    "request_timeout": 300,
    "notifications": False,
    "max_tokens": 16384,
    "context_warning": 60000,
    "log_level": "INFO",
    "log_max_bytes": 2_000_000,
    "log_backups": 3,
    "execution_isolation": "none",
    "isolate_network": False,
    "plugins": {},
    "hooks": {},
    "mcp_servers": {},
    "auto_compact": False,
    "model_context_limits": {},
    "model_costs": {},
    "reduce_motion": False,
    "accessible_icons": False,
    "credential_store": "file",
}

VALID_MODES = {"auto", "manual", "plan"}
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
INTEGER_LIMITS = {
    "shell_timeout": (1, 86_400),
    "max_iterations": (0, 10_000),
    "max_output_bytes": (1_024, 100_000_000),
    "request_timeout": (1, 86_400),
    "max_tokens": (512, 200_000),
    "context_warning": (0, 10_000_000),
    "log_max_bytes": (10_000, 100_000_000),
    "log_backups": (0, 20),
}


class Config:
    """Loaded config with atomic saves."""

    def __init__(self, data: dict[str, Any], path: Path):
        self.data = data
        self.path = path

    # loading

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or paths.config_file()
        data = _read(path)
        merged = _merge_defaults(data)
        return cls(merged, path)

    def save(self) -> None:
        _atomic_write(self.path, self.data)

    # generic access

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value

    # provider credentials

    def provider_config(self, name: str) -> dict[str, Any]:
        return self.data.setdefault("providers", {}).setdefault(name, {})

    def set_provider(self, name: str, *, api_key: str | None = None,
                     base_url: str | None = None, model: str | None = None) -> None:
        entry = self.provider_config(name)
        if api_key is not None:
            if self.get("credential_store") == "keyring" and api_key:
                from . import credentials
                credentials.set(name, api_key)
                entry.pop("api_key", None)
                entry["api_key_ref"] = "keyring"
            else:
                entry["api_key"] = api_key
                entry.pop("api_key_ref", None)
        if base_url is not None:
            entry["base_url"] = base_url
        if model is not None:
            entry["model"] = model

    def forget_provider(self, name: str) -> bool:
        entry = self.data.get("providers", {}).pop(name, None)
        if isinstance(entry, dict) and entry.get("api_key_ref") == "keyring":
            from . import credentials
            credentials.delete(name)
        return entry is not None

    def api_key(self, name: str) -> str | None:
        env = os.environ.get(f"EIRENE_{name.upper()}_API_KEY")
        if env:
            return env
        entry = self.provider_config(name)
        if entry.get("api_key_ref") == "keyring":
            from . import credentials
            return credentials.get(name)
        key = entry.get("api_key")
        return key or None

    def base_url(self, name: str) -> str | None:
        return self.provider_config(name).get("base_url") or None

    def configured_providers(self) -> list[str]:
        return sorted(self.data.get("providers", {}))

    # active selection

    @property
    def provider(self) -> str | None:
        return self.data.get("provider")

    @provider.setter
    def provider(self, name: str | None) -> None:
        self.data["provider"] = name

    @property
    def model(self) -> str | None:
        return self.data.get("model")

    @model.setter
    def model(self, name: str | None) -> None:
        self.data["model"] = name

    @property
    def mode(self) -> str:
        return self.data.get("mode", "manual")

    @mode.setter
    def mode(self, value: str) -> None:
        self.data["mode"] = value

    # skills

    def skill_enabled(self, name: str, default: bool = True) -> bool:
        return bool(self.data.setdefault("skills", {}).get(name, default))

    def set_skill(self, name: str, enabled: bool) -> None:
        self.data.setdefault("skills", {})[name] = bool(enabled)

    def plugin_enabled(self, name: str, default: bool = True) -> bool:
        return bool(self.data.setdefault("plugins", {}).get(name, default))

    def set_plugin(self, name: str, enabled: bool) -> None:
        self.data.setdefault("plugins", {})[name] = bool(enabled)


def _read(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"cannot read config: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        _quarantine(path)
        return {}
    if not isinstance(data, dict):
        _quarantine(path)
        return {}
    return data


def _quarantine(path: Path) -> None:
    """Move unreadable config aside."""
    try:
        shutil.copy2(path, path.with_suffix(".json.bak"))
    except OSError:
        pass


def _merge_defaults(data: dict[str, Any]) -> dict[str, Any]:
    data = _migrate(data)
    merged = json.loads(json.dumps(DEFAULTS))
    for key, value in data.items():
        merged[key] = value
    merged["version"] = CONFIG_VERSION
    if not isinstance(merged.get("providers"), dict):
        merged["providers"] = {}
    if not isinstance(merged.get("skills"), dict):
        merged["skills"] = {}
    for key in ("plugins", "hooks", "mcp_servers", "model_context_limits", "model_costs"):
        if not isinstance(merged.get(key), dict):
            merged[key] = {}
    merged["auto_compact"] = bool(merged.get("auto_compact", False))
    merged["reduce_motion"] = bool(merged.get("reduce_motion", False))
    merged["accessible_icons"] = bool(merged.get("accessible_icons", False))
    if merged.get("mode") not in VALID_MODES:
        merged["mode"] = "manual"
    level = str(merged.get("log_level", "INFO")).upper()
    merged["log_level"] = level if level in VALID_LOG_LEVELS else "INFO"
    isolation = str(merged.get("execution_isolation", "none")).lower()
    merged["execution_isolation"] = isolation if isolation in {"none", "bubblewrap"} else "none"
    store = str(merged.get("credential_store", "file")).lower()
    merged["credential_store"] = store if store in {"file", "keyring"} else "file"
    merged["isolate_network"] = bool(merged.get("isolate_network", False))
    for key, (minimum, maximum) in INTEGER_LIMITS.items():
        fallback = int(DEFAULTS[key])
        try:
            value = int(merged.get(key, fallback))
        except (TypeError, ValueError):
            value = fallback
        merged[key] = max(minimum, min(value, maximum))
    return merged


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Return a migrated copy; old config files are never mutated in place."""
    migrated = dict(data)
    try:
        version = int(migrated.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    if version < 2:
        # Version 2 introduced diagnostics/logging settings. Defaults supply
        # their values, so the migration only needs to advance the schema.
        version = 2
    migrated["version"] = min(max(version, 1), CONFIG_VERSION)
    return migrated


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    paths._tighten(path.parent)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if os.name != "nt":
            os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise ConfigError(f"cannot write config: {exc}") from exc
