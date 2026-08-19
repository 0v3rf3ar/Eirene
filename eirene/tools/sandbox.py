"""Working-directory containment."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from ..core.errors import SandboxError


class Sandbox:
    """Resolves paths against a fixed root."""

    def __init__(self, root: Path):
        self.root = Path(root).expanduser().resolve()
        self._permitted: set[Path] = set()

    def __str__(self) -> str:
        return str(self.root)

    def contains(self, path: Path | str) -> bool:
        try:
            self.resolve(path)
        except SandboxError:
            return False
        return True

    def resolve(self, path: Path | str) -> Path:
        """Resolve inside the root or raise."""
        raw = str(path).strip()
        if not raw:
            raise SandboxError("empty path")
        if raw.startswith("~"):
            raise SandboxError(f"'{raw}' is outside {self.root}")
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = self.root / candidate
        resolved = self._resolve_strict(candidate)
        if (resolved != self.root and self.root not in resolved.parents
                and not self.permitted(resolved)):
            raise SandboxError(f"'{raw}' is outside {self.root}")
        return resolved

    def permitted(self, resolved: Path) -> bool:
        """True while the user has approved this path for the running tool."""
        return any(resolved == allowed or allowed in resolved.parents
                   for allowed in self._permitted)

    @contextmanager
    def permit(self, *paths: str) -> Iterator[None]:
        """Let one approved call reach outside the root, then close it again."""
        granted: set[Path] = set()
        for path in paths:
            raw = str(path or "").strip()
            if not raw:
                continue
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = self.root / candidate
            try:
                granted.add(self._resolve_strict(candidate))
            except SandboxError:
                continue
        self._permitted |= granted
        try:
            yield
        finally:
            self._permitted -= granted

    def relative(self, path: Path | str) -> str:
        """Display path relative to root."""
        try:
            return str(Path(path).resolve().relative_to(self.root)) or "."
        except (ValueError, OSError):
            return str(path)

    def _resolve_strict(self, candidate: Path) -> Path:
        """Resolve symlinks even for missing files."""
        try:
            return candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise SandboxError(f"cannot resolve '{candidate}': {exc}") from exc

    def check_write_target(self, path: Path | str) -> Path:
        """Resolve and reject links escaping root."""
        resolved = self.resolve(path)
        parent = resolved.parent
        if parent.exists() and not parent.is_dir():
            raise SandboxError(f"'{self.relative(parent)}' is not a directory")
        return resolved


def default_root() -> Path:
    return Path(os.getcwd()).resolve()
