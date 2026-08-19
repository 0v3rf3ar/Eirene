import re
import sys
from pathlib import Path

APP_NAME = "eirene"
_FALLBACK = "0.0.0"


def _manifest() -> Path:
    """Where pyproject.toml lives, frozen or not."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / "pyproject.toml"
    return Path(__file__).resolve().parent.parent / "pyproject.toml"


def _read_version() -> str:
    """The version declared in pyproject.toml."""
    try:
        text = _manifest().read_text(encoding="utf-8")
    except OSError:
        return _FALLBACK
    body = text.split("[project]", 1)[-1].split("\n[", 1)[0]
    found = re.search(r'^\s*version\s*=\s*["\']([^"\']+)["\']', body, re.M)
    return found.group(1) if found else _FALLBACK


__version__ = _read_version()
