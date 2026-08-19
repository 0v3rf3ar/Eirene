"""Private structured runtime logging."""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import platform
import sys
import time
from pathlib import Path
from typing import Any

from . import paths

LOGGER_NAME = "eirene"
_configured: Path | None = None


class JsonFormatter(logging.Formatter):
    """One compact JSON object per event, suitable for diagnostics."""

    _standard = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}

    def format(self, record: logging.LogRecord) -> str:
        body: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in self._standard and not key.startswith("_"):
                try:
                    json.dumps(value)
                    body[key] = value
                except (TypeError, ValueError):
                    body[key] = repr(value)
        if record.exc_info:
            body["exception"] = self.formatException(record.exc_info)
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


def configure(config) -> logging.Logger:
    """Configure the application logger once for the active data directory."""
    global _configured
    target = paths.runtime_log()
    logger = logging.getLogger(LOGGER_NAME)
    if _configured == target and logger.handlers:
        return logger
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)
    paths.ensure_tree()
    handler = logging.handlers.RotatingFileHandler(
        target, maxBytes=int(config.get("log_max_bytes", 2_000_000)),
        backupCount=int(config.get("log_backups", 3)), encoding="utf-8")
    if os.name != "nt":
        try:
            target.chmod(0o600)
        except OSError:
            pass
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(str(config.get("log_level", "INFO")).upper())
    logger.propagate = False
    _configured = target
    logger.info("runtime.started", extra={"python": platform.python_version(),
                                           "platform": sys.platform})
    return logger


def get() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
