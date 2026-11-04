"""Typed errors with user-safe messages."""

from __future__ import annotations


class EireneError(Exception):
    """Base for all handled errors."""

    def user_message(self) -> str:
        return str(self)


class SandboxError(EireneError):
    """Path or command left the sandbox."""


class ToolError(EireneError):
    """Tool refused or failed."""


class ConfigError(EireneError):
    """Config could not be read or written."""


class SessionError(EireneError):
    """Session file problem."""


class ProviderError(EireneError):
    """Base for provider failures."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class AuthError(ProviderError):
    """Key missing or rejected."""

    def __init__(self, message: str = "API key rejected", status: int | None = 401):
        super().__init__(message, retryable=False, status=status)


class RateLimitError(ProviderError):
    """Provider rate limited us."""

    def __init__(self, message: str = "rate limited", retry_after: float | None = None):
        super().__init__(message, retryable=True, status=429)
        self.retry_after = retry_after


class ConnectionFailed(ProviderError):
    """Host unreachable."""

    def __init__(self, host: str, detail: str = ""):
        msg = f"cannot reach {host}"
        if detail:
            msg = f"{msg} ({detail})"
        super().__init__(msg, retryable=True)


class ModelNotFound(ProviderError):
    """Model name rejected."""

    def __init__(self, model: str):
        super().__init__(f"model '{model}' not available", retryable=False, status=404)


class SchedulerError(EireneError):
    """Scheduling backend failure."""


class CommandError(EireneError):
    """Slash command misuse."""


class Cancelled(EireneError):
    """User cancelled the turn."""

    def __init__(self, message: str = "cancelled"):
        super().__init__(message)


def error_kind(exc: BaseException) -> str:
    """Coarse failure class for scripts: config, auth, network, provider, tool or failed."""
    # Retries rewrap the last provider failure with advice; classify the original.
    while type(exc) is ProviderError and isinstance(exc.__cause__, ProviderError):
        exc = exc.__cause__
    if isinstance(exc, AuthError):
        return "auth"
    if isinstance(exc, (ModelNotFound, ConfigError)):
        return "config"
    if isinstance(exc, ProviderError):
        if exc.retryable or isinstance(exc, ConnectionFailed) or (exc.status or 0) >= 500:
            return "network"
        return "provider"
    if isinstance(exc, (SandboxError, ToolError)):
        return "tool"
    return "failed"
