"""Import portable plugin bundles without executing repository installers."""

from __future__ import annotations

from .subprocesses import external_environment

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


# Windows cannot create files or folders with these names, with or without an extension.
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                    *(f"lpt{n}" for n in range(1, 10))}


def _require_portable(name: str) -> None:
    if name.split(".", 1)[0].casefold() in WINDOWS_RESERVED or name.endswith("."):
        raise ValueError(f"plugin name {name!r} cannot be used as a folder name on Windows")


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
            environment = external_environment()
            environment["GIT_TERMINAL_PROMPT"] = "0"
            try:
                # Keep files byte-for-byte as published: Git for Windows would
                # otherwise convert hook scripts to CRLF, which bash cannot run.
                result = subprocess.run(
                    ["git", "-c", "core.hooksPath=", "-c", "core.autocrlf=false", "clone", "--depth", "1",
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
        _require_portable(name)
        # Preserve relative references and licenses, but never follow repository symlinks.
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [entry for entry in dirs if entry != ".git"]
            if any((Path(directory) / entry).is_symlink() for entry in dirs + files):
                raise ValueError("repositories containing symlinks are not supported")
        manifest = normalize(root, name)
        _require_portable(manifest["name"])
        shortcut = next((slug for slug, _, _ in BUNDLES if slug.casefold() == source.casefold()), "")
        if shortcut:
            manifest["catalog_shortcut"] = shortcut
        name = manifest["name"]
        destination = paths.plugins_dir() / name
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"{name} is already installed; existing files were preserved")
        skill_folder = paths.skills_dir() / name
        if manifest["skills"] and (skill_folder.exists() or skill_folder.is_symlink()):
            raise ValueError(f"skills folder {skill_folder} already exists; existing files were preserved")
        if not any(manifest[key] for key in ("skills", "commands", "agents", "lifecycle", "mcp_servers")):
            raise ValueError("no skills, commands, hooks, or MCP servers found")
        paths.plugins_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=paths.plugins_dir()) as staging:
            copied = Path(staging) / "plugin"
            shutil.copytree(root, copied, ignore=shutil.ignore_patterns(".git"))
            if manifest["skills"]:
                manifest["skills_exported"] = True
            (copied / ".eirene-plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            copied.rename(destination)
        if manifest["skills"]:
            export_skills(name, destination, manifest["skills"])
        return name, len(manifest["skills"])


def export_skills(name: str, root: Path, skills: list[str]) -> Path:
    """Copy a bundle's skills into skills/<name>/; the bundle keeps its own copy for hooks."""
    target = paths.skills_dir() / name
    if target.exists() or target.is_symlink():
        raise ValueError(f"skills folder {target} already exists; existing files were preserved")
    paths.skills_dir().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".install-", dir=paths.skills_dir()) as staging:
        folder = Path(staging) / name
        folder.mkdir()
        for relative in skills:
            source = root / relative
            if source.name == "SKILL.md":
                copy = folder / source.parent.name
                if not copy.exists():
                    shutil.copytree(source.parent, copy,
                                    ignore=shutil.ignore_patterns(".git", ".eirene-plugin.json"))
            elif not (folder / source.name).exists():
                shutil.copy2(source, folder / source.name)
        folder.rename(target)
    return target


def export_installed_skills() -> list[str]:
    """Give plugins installed before skill folders existed their skills/<name>/ group."""
    moved = []
    for root in sorted(paths.plugins_dir().glob("*/.eirene-plugin.json")):
        try:
            manifest = json.loads(root.read_text(encoding="utf-8"))
            if manifest.get("skills_exported") or not manifest.get("skills"):
                continue
            name = str(manifest.get("name") or root.parent.name)
            if not (paths.skills_dir() / name).exists():
                export_skills(name, root.parent, manifest["skills"])
                moved.append(name)
            manifest["skills_exported"] = True
            temporary = root.with_name(".plugin.json.tmp")
            temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            temporary.replace(root)
        except (OSError, TypeError, ValueError):
            continue
    return moved
