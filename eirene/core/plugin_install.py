"""Import portable plugin bundles without executing repository installers."""

from __future__ import annotations

from .subprocesses import external_environment

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading

from . import paths
from .plugin_manifest import inside, normalize
from .plugin_catalog import BUNDLES, SHIPPED_REPOSITORY_FOLDER, source_for
from .updates import REPOSITORY


def bundled_skills(name: str = "eirene-skills") -> Path:
    """A bundle shipped inside the package (or the frozen executable)."""
    root = Path(__file__).resolve().parent.parent / "plugins" / name
    if not (root / "plugin.json").is_file():
        raise ValueError(f"the bundled {name} files are missing from this installation")
    return root


def _copy_shipped(name: str, destination: Path) -> None:
    """Copy a shipped bundle; packaging can drop the executable bit its scripts need."""
    shutil.copytree(bundled_skills(name), destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    _restore_executable_bits(destination)


def _restore_executable_bits(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file() and path.parent.name in ("hooks", "scripts") and path.suffix not in (".json", ".md", ".html"):
            path.chmod(path.stat().st_mode | 0o111)


def github_source(source: str) -> tuple[str, str, str, str | None]:
    """Parse GitHub bundles, including subdirectories and tree URLs."""
    match = re.fullmatch(
        r"(?:https://github\.com/)?([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?(?:/(.*))?",
        source,
    )
    if not match or any(part in (".", "..") for part in match.groups()[:2]):
        raise ValueError("use a local directory, catalog name, name@marketplace, owner/repo[/path], or GitHub tree URL")
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


@dataclass
class UpdateResult:
    changed: bool = False
    skills: int = 0
    # Where the previous skills folder was saved, when it may have held edits.
    backup: Path | None = None


GIT_TIMEOUT = 120


# Windows cannot create files or folders with these names, with or without an extension.
WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)),
                    *(f"lpt{n}" for n in range(1, 10))}


def _require_portable(name: str) -> None:
    if name.split(".", 1)[0].casefold() in WINDOWS_RESERVED or name.endswith("."):
        raise ValueError(f"plugin name {name!r} cannot be used as a folder name on Windows")


# One step of a download: what is happening, and how far along the whole job is (0 to 1).
Progress = Callable[[str, float], None]


def scaled(progress: Progress | None, start: float, end: float) -> Progress | None:
    """Report a part of a job as its own 0-to-1, inside the whole job's bar."""
    if progress is None:
        return None
    return lambda stage, fraction: progress(stage, start + (end - start) * fraction)


# How much of one Git download each of its phases covers.
_GIT_PHASES = {"Counting": (0, .05), "Compressing": (.05, .1), "Receiving": (.1, .85),
               "Resolving": (.85, .95), "Updating": (.95, 1), "Filtering": (.95, 1)}
_GIT_PROGRESS = re.compile(r"(?:remote: )?((" + "|".join(_GIT_PHASES) + r")\b[^:]*):\s+(\d+)%")
_GIT_CHATTER = re.compile(r"(?:remote: )?(?:Enumerating|Total|Counting|Compressing|Receiving|Resolving"
                          r"|Updating|Filtering|Cloning into)\b")


_GIT_NO_ACCESS = re.compile(r"could not read (?:Username|Password)|terminal prompts disabled"
                            r"|repository .* not found|Repository not found", re.IGNORECASE)


def clone(url: str, destination: Path, *, ref: str = "", sha: str = "",
          progress: Progress | None = None) -> None:
    """Shallow-clone without credential prompts; ``sha`` pins an exact commit."""
    environment = external_environment()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    # Progress lines are matched by their English text.
    environment["LC_ALL"] = "C"
    environment.pop("LANGUAGE", None)

    def git(*arguments: str, cwd: Path | None = None, report: Progress | None = None) -> None:
        # Keep files byte-for-byte as published: Git for Windows would
        # otherwise convert hook scripts to CRLF, which bash cannot run.
        try:
            process = subprocess.Popen(
                ["git", "-c", "core.hooksPath=", "-c", "core.autocrlf=false", *arguments],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                text=True, errors="replace", env=environment, cwd=cwd,
            )
        except FileNotFoundError as exc:
            raise ValueError("Git is required to install from a repository") from exc
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            process.kill()

        watchdog = threading.Timer(GIT_TIMEOUT, expire)
        watchdog.start()
        errors = []
        try:
            # Text mode splits Git's carriage-returned progress updates into lines.
            for line in process.stderr:
                line = line.strip()
                match = _GIT_PROGRESS.match(line)
                if match and report:
                    start, end = _GIT_PHASES[match.group(2)]
                    report(match.group(1), start + (end - start) * int(match.group(3)) / 100)
                elif line and not _GIT_CHATTER.match(line):
                    errors.append(line)
            code = process.wait()
        finally:
            watchdog.cancel()
            process.stderr.close()
        if expired.is_set():
            raise ValueError("repository download timed out")
        if code:
            detail = "\n".join(errors)
            # GitHub answers the same for a missing repository and a private one, and
            # Git then asks for a login it is not allowed to prompt for.
            if _GIT_NO_ACCESS.search(detail):
                raise ValueError(f"repository not found, or it is private: {url}. "
                                 "Check the name; a private repository needs Git authentication set up first.")
            raise ValueError("could not download repository: " + detail)

    git("clone", "--progress", "--depth", "1", *(["--no-checkout"] if sha else []),
        *(["--branch", ref] if ref and not sha else []), "--", url, str(destination),
        report=scaled(progress, 0, .45 if sha else 1))
    if sha:
        git("fetch", "--progress", "--depth", "1", "origin", sha, cwd=destination, report=scaled(progress, .45, .9))
        git("checkout", "--progress", "--detach", sha, cwd=destination, report=scaled(progress, .9, 1))


def selected_directory(root: Path, subdirectory: str) -> Path:
    """A folder inside ``root``; rejects symlink ancestors, even ones targeting the same repo."""
    relative = Path(subdirectory)
    if any((root / Path(*relative.parts[:index])).is_symlink()
           for index in range(1, len(relative.parts) + 1)):
        raise ValueError("repositories containing symlinks are not supported")
    selected = inside(root, subdirectory)
    if not selected.is_dir():
        raise ValueError(f"plugin subdirectory not found: {subdirectory}")
    return selected


def install(source: str, *, replacing=None, outcome: UpdateResult | None = None,
            progress: Progress | None = None) -> tuple[str, int]:
    """Install a local, marketplace, or GitHub portable plugin bundle.

    ``replacing`` is an installed plugin to swap for the download, keeping its name.
    Call ``update`` for that: it fills in ``outcome`` with what happened.
    """
    download = scaled(progress, 0, .9)
    source = source.strip()
    local = Path(source).expanduser()
    entry = None
    market = ""
    with tempfile.TemporaryDirectory(prefix="eirene-plugin-") as temporary:
        # Windows may spell %TEMP% with 8.3 short names (PLYGRN~1), which later resolved
        # paths inside it would not share.
        temporary = str(Path(temporary).resolve())
        listed = None
        if not local.is_dir() and source_for(source) == source:
            from . import marketplace
            listed = marketplace.resolve(source)
        if local.is_dir():
            root = local.resolve()
            name = root.name
        elif listed:
            catalog, entry = listed
            market = catalog.name
            name = entry["name"]
            root = marketplace.materialize(catalog, entry, Path(temporary), download)
        elif source_for(source) == "builtin:omniroute":
            from .omniroute_mcp import manifest
            name = "omniroute"
            root = Path(temporary) / name
            root.mkdir()
            (root / "plugin.json").write_text(json.dumps(manifest(), indent=2) + "\n", encoding="utf-8")
        elif source_for(source).startswith("builtin:"):
            name = source_for(source).removeprefix("builtin:")
            if replacing is None:
                root = Path(temporary) / name
                _copy_shipped(name, root)
            else:
                # An update wants the newest copy, not the one this version of Eirene shipped with.
                root = Path(temporary) / "repo"
                clone(f"https://github.com/{REPOSITORY}.git", root, progress=download)
                root = selected_directory(root, f"{SHIPPED_REPOSITORY_FOLDER}/{name}")
                _restore_executable_bits(root)
        else:
            owner, name, subdirectory, ref = github_source(source_for(source))
            root = Path(temporary) / "repo"
            clone(f"https://github.com/{owner}/{name}.git", root, ref=ref or "", progress=download)
            if subdirectory:
                root = selected_directory(root, subdirectory)
                name = root.name

        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", name):
            raise ValueError("repository directory must have a simple alphanumeric name")
        _require_portable(name)
        # Preserve relative references and licenses, but never follow repository symlinks.
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [entry for entry in dirs if entry != ".git"]
            if any((Path(directory) / entry).is_symlink() for entry in dirs + files):
                raise ValueError("repositories containing symlinks are not supported")
        manifest = normalize(root, name, entry)
        _require_portable(manifest["name"])
        if entry is not None:
            # Kept so /plugins refresh rebuilds the same selection from the same entry.
            manifest["marketplace"] = market
            manifest["marketplace_entry"] = entry
        manifest["install_source"] = str(local.resolve()) if local.is_dir() else \
            f"{entry['name']}@{market}" if entry is not None else source
        shortcut = next((slug for slug, _, _ in BUNDLES if slug.casefold() == source.casefold()), "")
        if shortcut:
            manifest["catalog_shortcut"] = shortcut
        if replacing is not None:
            # Upstream may rename itself; the installed identity holds its settings.
            manifest["name"] = replacing.name
        name = manifest["name"]
        destination = paths.plugins_dir() / name
        old_index = _read_index(destination) if replacing is not None else {}
        if replacing is None and (destination.exists() or destination.is_symlink()):
            raise ValueError(f"{name} is already installed; existing files were preserved")
        skill_folder = paths.skills_dir() / name
        if manifest["skills"] and not old_index.get("skills_exported") \
                and (skill_folder.exists() or skill_folder.is_symlink()):
            raise ValueError(f"skills folder {skill_folder} already exists; existing files were preserved")
        if not any(manifest[key] for key in ("skills", "commands", "agents", "lifecycle", "mcp_servers")):
            raise ValueError("no skills, commands, hooks, or MCP servers found")
        if progress:
            progress("Copying files", .95)
        paths.plugins_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".install-", dir=paths.plugins_dir()) as staging:
            copied = Path(staging) / "plugin"
            shutil.copytree(root, copied, ignore=shutil.ignore_patterns(".git"))
            if manifest["skills"]:
                manifest["skills_exported"] = True
            if replacing is not None:
                if _tree_digest(copied) == _tree_digest(destination) \
                        and all(manifest.get(key) == old_index.get(key) for key in _DECLARED):
                    return name, len(manifest["skills"])
                backup = _swap(name, destination, copied, Path(staging), old_index, manifest)
                if outcome is not None:
                    outcome.changed, outcome.skills, outcome.backup = True, len(manifest["skills"]), backup
                return name, len(manifest["skills"])
            _write_index(copied, manifest)
            copied.rename(destination)
            if manifest["skills"]:
                export_skills(name, destination, manifest["skills"])
                manifest["skills_digest"] = _tree_digest(skill_folder)
                _write_index(destination, manifest)
        return name, len(manifest["skills"])


# Index fields that change what a plugin does, beside the files themselves.
_DECLARED = ("description", "skills", "commands", "agents", "lifecycle", "mcp_servers", "marketplace_entry")


def _read_index(root: Path) -> dict:
    try:
        index = json.loads((root / ".eirene-plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return index if isinstance(index, dict) else {}


def _write_index(root: Path, manifest: dict) -> None:
    (root / ".eirene-plugin.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def _tree_digest(root: Path) -> str:
    """A fingerprint of a folder's files, ignoring Eirene's index and bytecode."""
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != ".eirene-plugin.json" and "__pycache__" not in path.parts:
            digest.update(path.relative_to(root).as_posix().encode() + b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _swap(name: str, destination: Path, copied: Path, staging: Path, old_index: dict,
          manifest: dict) -> Path | None:
    """Put a new copy in place, restoring the old plugin and skills if anything fails.

    Returns where the previous skills folder was saved, when it may have held edits.
    """
    exported = paths.skills_dir() / name
    moved_skills = old_index.get("skills_exported") and exported.is_dir() and not exported.is_symlink()
    old_plugin, old_skills = staging / "old-plugin", staging / "old-skills"
    backup = None
    if moved_skills and _tree_digest(exported) != old_index.get("skills_digest"):
        # Edited, or installed before digests were kept. Never drop someone's changes.
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = paths.home() / "plugin-data" / name / f"skills-backup-{stamp}"
        shutil.copytree(exported, backup)
    destination.rename(old_plugin)
    try:
        if moved_skills:
            shutil.move(str(exported), str(old_skills))
        _write_index(copied, manifest)
        copied.rename(destination)
        if manifest["skills"]:
            export_skills(name, destination, manifest["skills"])
            manifest["skills_digest"] = _tree_digest(exported)
            _write_index(destination, manifest)
    except Exception:
        if exported.exists() and (moved_skills or manifest["skills"]):
            shutil.rmtree(exported)
        if old_skills.exists():
            shutil.move(str(old_skills), str(exported))
        if destination.exists():
            shutil.rmtree(destination)
        old_plugin.rename(destination)
        raise
    return backup


def update(plugin, *, refreshed: set[str] | None = None, progress: Progress | None = None) -> UpdateResult:
    """Download an installed plugin again from where it came from and swap it in.

    ``refreshed`` names marketplaces already re-downloaded in this run.
    """
    index = _read_index(plugin.path)
    # Installs from before origins were recorded can still follow a current shortcut.
    shortcut = plugin.catalog_shortcut if any(slug == plugin.catalog_shortcut for slug, _, _ in BUNDLES) else ""
    source = index.get("install_source") or shortcut
    if not source:
        raise ValueError("it was installed before updates were tracked; "
                         f"run /plugin uninstall {plugin.name}, then install it again")
    if plugin.marketplace and plugin.marketplace not in (refreshed or ()):
        from . import marketplace
        marketplace.update(plugin.marketplace, progress=scaled(progress, 0, .3))
        if refreshed is not None:
            refreshed.add(plugin.marketplace)
    outcome = UpdateResult()
    install(str(source), replacing=plugin, outcome=outcome, progress=scaled(progress, .3, 1))
    return outcome


def uninstall(plugin) -> None:
    """Delete an installed bundle and its exported skills folder."""
    root = plugin.path
    if root.parent.resolve() != paths.plugins_dir().resolve():
        raise ValueError(f"{plugin.name} is not in the plugins folder; remove {root} yourself")
    index = _read_index(root)
    # Only a folder the installer exported: a user's own skills/<name>/ is not ours to delete.
    exported = paths.skills_dir() / root.name
    if index.get("skills_exported"):
        if exported.is_symlink():
            exported.unlink()
        elif exported.is_dir():
            shutil.rmtree(exported)
    shutil.rmtree(root)


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
