"""Import portable plugin bundles without executing repository installers."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from . import paths
from .plugin_manifest import inside, normalize
from .plugin_catalog import BUNDLES, source_for


def github_source(source: str) -> tuple[str, str, str, str | None]:
    """Parse GitHub bundles, including subdirectories and tree URLs."""
    match = re.fullmatch(
        r"(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/(.*))?",
        source,
    )
    if not match or any(part in (".", "..") for part in match.groups()[:2]):
        raise ValueError("use a local directory, catalog name, owner/repo[/path], or GitHub tree URL")
    owner, repository, subdirectory = match.groups()
    ref = None
    subdirectory = (subdirectory or "").rstrip("/")
    if subdirectory.startswith("tree/"):
        parts = subdirectory.split("/", 2)
        if len(parts) != 3:
            raise ValueError("GitHub tree URLs must include a branch/tag and plugin directory")
        _, ref, subdirectory = parts
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", ref) or ref in (".", ".."):
            raise ValueError("invalid GitHub branch/tag")
    if subdirectory and any(not re.fullmatch(r"[A-Za-z0-9_.-]+", part) or part in (".", "..", ".git")
                            for part in subdirectory.split("/")):
        raise ValueError("invalid plugin subdirectory")
    return owner, repository, subdirectory, ref


def install(source: str) -> tuple[str, int]:
    """Install a local or GitHub portable plugin bundle."""
    source = source.strip()
    local = Path(source).expanduser()
    with tempfile.TemporaryDirectory(prefix="eirene-plugin-") as temporary:
        if local.is_dir():
            root = local.resolve()
            name = root.name
        elif source_for(source) == "builtin:omniroute":
            from .omniroute_mcp import manifest
            name = "omniroute"
            root = Path(temporary) / name
            root.mkdir()
            (root / "plugin.json").write_text(json.dumps(manifest(), indent=2) + "\n", encoding="utf-8")
        else:
            owner, name, subdirectory, ref = github_source(source_for(source))
            root = Path(temporary) / "repo"
            environment = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            try:
                result = subprocess.run(
                    ["git", "-c", "core.hooksPath=", "clone", "--depth", "1",
                     *(["--branch", ref] if ref else []), "--",
                     f"https://github.com/{owner}/{name}.git", str(root)],
                    capture_output=True, text=True, timeout=120, env=environment,
                )
            except FileNotFoundError as exc:
                raise ValueError("Git is required to install from GitHub") from exc
            except subprocess.TimeoutExpired as exc:
                raise ValueError("repository download timed out") from exc
            if result.returncode:
                raise ValueError(f"could not download repository: {result.stderr.strip()}")
            if subdirectory:
                # Reject symlink ancestors, even if they target another path in the repo.
                relative = Path(subdirectory)
                if any((root / Path(*relative.parts[:index])).is_symlink()
                       for index in range(1, len(relative.parts) + 1)):
                    raise ValueError("repositories containing symlinks are not supported")
                selected = inside(root, subdirectory)
                if not selected.is_dir():
                    raise ValueError(f"plugin subdirectory not found: {subdirectory}")
                root = selected
                name = root.name

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("repository directory must have a simple alphanumeric name")
        # Preserve relative references and licenses, but never follow repository symlinks.
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [entry for entry in dirs if entry != ".git"]
            if any((Path(directory) / entry).is_symlink() for entry in dirs + files):
                raise ValueError("repositories containing symlinks are not supported")
        manifest = normalize(root, name)
        shortcut = next((slug for slug, _, _ in BUNDLES if slug.casefold() == source.casefold()), "")
        if shortcut:
            manifest["catalog_shortcut"] = shortcut
        name = manifest["name"]
        destination = paths.plugins_dir() / name
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"{name} is already installed; existing files were preserved")
        if not any(manifest[key] for key in ("skills", "commands", "agents", "lifecycle", "mcp_servers")):
            raise ValueError("no skills, commands, hooks, or MCP servers found")
        paths.plugins_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=paths.plugins_dir()) as staging:
            copied = Path(staging) / "plugin"
            shutil.copytree(root, copied, ignore=shutil.ignore_patterns(".git"))
            (copied / ".eirene-plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            copied.rename(destination)
        return name, len(manifest["skills"])
