"""Optional operating-system credential storage through keyring."""

from __future__ import annotations

from .errors import ConfigError

SERVICE = "eirene"


def available() -> bool:
    try:
        import keyring
        backend = keyring.get_keyring()
        return getattr(backend, "priority", 0) > 0
    except (ImportError, Exception):
        return False


def get(name: str) -> str | None:
    try:
        import keyring
        return keyring.get_password(SERVICE, name) or None
    except ImportError as exc:
        raise ConfigError("credential_store is keyring but keyring is not installed") from exc
    except Exception as exc:
        raise ConfigError(f"cannot read the OS credential store: {exc}") from exc


def set(name: str, secret: str) -> None:
    try:
        import keyring
        keyring.set_password(SERVICE, name, secret)
    except ImportError as exc:
        raise ConfigError("credential_store is keyring but keyring is not installed") from exc
    except Exception as exc:
        raise ConfigError(f"cannot write the OS credential store: {exc}") from exc


def delete(name: str) -> None:
    try:
        import keyring
        keyring.delete_password(SERVICE, name)
    except ImportError:
        return
    except Exception:
        return
