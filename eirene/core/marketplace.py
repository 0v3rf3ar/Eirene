"""Plugin marketplaces: catalogs of installable bundles, added by source.

A marketplace is a repository or folder holding a ``marketplace.json``, in the
format Claude Code and Codex publish. Adding one only records its catalog;
nothing in it runs and no plugin is installed until asked for by name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import paths
from .plugin_manifest import read_object

MANIFESTS = (".claude-plugin/marketplace.json", ".agents/plugins/marketplace.json",
             ".codex-plugin/marketplace.json", ".github/plugin/marketplace.json", "marketplace.json")
NAME = r"[A-Za-z0-9][A-Za-z0-9_.-]*"
_REF = r"[A-Za-z0-9][A-Za-z0-9_./-]*"
_SHA = r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?"


@dataclass
class Marketplace:
    name: str
    source: str
    root: Path
    description: str = ""
    plugin_root: str = ""
    plugins: list[dict] = field(default_factory=list)
    error: str = ""


def directory() -> Path:
    return paths.home() / "marketplaces"


def _registry() -> Path:
    return directory() / "known.json"


def _read_registry() -> dict[str, dict]:
    try:
        value = json.loads(_registry().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {name: entry for name, entry in value.items() if isinstance(entry, dict)} if isinstance(value, dict) else {}


def _write_registry(entries: dict[str, dict]) -> None:
    directory().mkdir(parents=True, exist_ok=True)
    temporary = _registry().with_suffix(".tmp")
    temporary.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    temporary.replace(_registry())


def git_url(value: str) -> str:
    """A clonable address, refusing transports that could run helper commands."""
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value) and not value.startswith((".", "-")):
        return f"https://github.com/{value.removesuffix('.git')}.git"
    if re.fullmatch(r"https://[^\s/@]+\.[^\s/@]+(?::\d+)?/[^\s@]+", value):
        return value
    if re.fullmatch(r"git@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+", value):
        return value
    raise ValueError(f"unsupported repository address: {value}")


def _parse_source(source: str) -> tuple[str, str, str]:
    """(git url, ref, local folder); exactly one of url and folder is set."""
    source = source.strip()
    if not source:
        raise ValueError("usage: /plugin marketplace add <owner/repo, git URL, or local folder>")
    local = Path(source).expanduser()
    if local.is_dir():
        return "", "", str(local.resolve())
    address, _, ref = source.partition("#")
    if ref and not re.fullmatch(_REF, ref):
        raise ValueError("invalid marketplace branch or tag")
    if address.endswith(".json"):
        raise ValueError("give the repository that holds marketplace.json, not the file")
    try:
        return git_url(address), ref, ""
    except ValueError:
        raise ValueError(f"not a local folder, owner/repo, or git URL: {source}") from None


def _manifest(root: Path) -> Path | None:
    return next((root / item for item in MANIFESTS if (root / item).is_file()), None)


def _load(name: str, source: str, root: Path) -> Marketplace:
    """Read a catalog, keeping only entries that name something installable."""
    manifest = _manifest(root)
    if manifest is None:
        raise ValueError("no marketplace.json found; if this is a single plugin, "
                         f"use /plugin install {source}")
    body = read_object(manifest)
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}
    entries, seen = [], set()
    for entry in body.get("plugins", []) if isinstance(body.get("plugins"), list) else []:
        if isinstance(entry, dict) and isinstance(entry.get("name"), str) \
                and re.fullmatch(NAME, entry["name"]) and "source" in entry and entry["name"] not in seen:
            seen.add(entry["name"])
            entries.append(entry)
    return Marketplace(name or str(body.get("name", "")), source, root,
                       str(body.get("description") or metadata.get("description") or ""),
                       str(metadata.get("pluginRoot") or ""), entries)


def known() -> list[Marketplace]:
    """Every added marketplace; an unreadable one is returned with its error."""
    found = []
    for name, entry in sorted(_read_registry().items()):
        root = Path(entry["path"]) if entry.get("path") else directory() / name
        try:
            found.append(_load(name, str(entry.get("source", "")), root))
        except (OSError, ValueError) as exc:
            found.append(Marketplace(name, str(entry.get("source", "")), root, error=str(exc)))
    return found


def _fetch(url: str, ref: str, name: str, progress=None) -> Marketplace:
    """Clone a catalog and put it in place, replacing any earlier copy of ``name``."""
    from .plugin_install import _require_portable, clone, scaled
    directory().mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".fetch-", dir=directory()) as staging:
        checkout = Path(staging) / "repo"
        clone(url, checkout, ref=ref, progress=scaled(progress, 0, .95))
        loaded = _load(name, url, checkout)
        if not re.fullmatch(NAME, loaded.name) or loaded.name == "known.json":
            raise ValueError("marketplace must have a simple alphanumeric name")
        _require_portable(loaded.name)
        if not name:
            existing = _read_registry().get(loaded.name)
            if existing is not None:
                raise ValueError(f"marketplace {loaded.name} is already added from {existing.get('source')}")
        if progress:
            progress("Saving catalog", .97)
        # Symlinks stay links here: installing a plugin that contains one is refused.
        copied = Path(staging) / "copy"
        shutil.copytree(checkout, copied, symlinks=True, ignore=shutil.ignore_patterns(".git"))
        destination = directory() / loaded.name
        if destination.exists():
            shutil.rmtree(destination)
        copied.rename(destination)
    loaded.root = destination
    return loaded


def add(source: str, progress=None) -> Marketplace:
    url, ref, folder = _parse_source(source)
    entries = _read_registry()
    for name, entry in entries.items():
        if (entry.get("path") or entry.get("source")) == (folder or url) and entry.get("ref", "") == ref:
            raise ValueError(f"marketplace {name} is already added")
    if folder:
        loaded = _load("", folder, Path(folder))
        from .plugin_install import _require_portable
        if not re.fullmatch(NAME, loaded.name):
            raise ValueError("marketplace must have a simple alphanumeric name")
        _require_portable(loaded.name)
        if loaded.name in entries:
            raise ValueError(f"marketplace {loaded.name} is already added from {entries[loaded.name].get('source')}")
        entries[loaded.name] = {"source": folder, "path": folder}
    else:
        loaded = _fetch(url, ref, "", progress)
        entries[loaded.name] = {"source": url, **({"ref": ref} if ref else {})}
    _write_registry(entries)
    return loaded


def update(name: str = "", progress=None) -> list[Marketplace]:
    """Download the catalog again. Installed plugins are left as they are."""
    from .plugin_install import scaled
    entries = _read_registry()
    if name and name not in entries:
        raise ValueError(f"marketplace not found: {name}")
    updated = []
    keys = [name] if name else sorted(entries)
    for position, key in enumerate(keys):
        entry = entries[key]
        if entry.get("path"):
            updated.append(_load(key, str(entry["source"]), Path(entry["path"])))
        else:
            part = scaled(progress, position / len(keys), (position + 1) / len(keys))
            updated.append(_fetch(str(entry["source"]), str(entry.get("ref", "")), key, part))
    return updated


def remove(name: str) -> None:
    """Forget a catalog. A local folder is only unlisted, never deleted."""
    entries = _read_registry()
    entry = entries.pop(name, None)
    if entry is None:
        raise ValueError(f"marketplace not found: {name}")
    _write_registry(entries)
    if not entry.get("path") and re.fullmatch(NAME, name) and (directory() / name).is_dir():
        shutil.rmtree(directory() / name)


def resolve(wanted: str) -> tuple[Marketplace, dict] | None:
    """Find ``plugin@marketplace``, or a bare ``plugin`` listed by just one marketplace."""
    plugin, at, market = wanted.partition("@")
    if not re.fullmatch(NAME, plugin) or (at and not re.fullmatch(NAME, market)):
        return None
    catalogs = known()
    if at:
        catalog = next((item for item in catalogs if item.name == market), None)
        if catalog is None:
            raise ValueError(f"marketplace not found: {market}; add it with /plugin marketplace add")
        if catalog.error:
            raise ValueError(f"marketplace {market} cannot be read: {catalog.error}")
        entry = next((item for item in catalog.plugins if item["name"] == plugin), None)
        if entry is None:
            raise ValueError(f"{market} does not list a plugin named {plugin}")
        return catalog, entry
    matches = [(catalog, entry) for catalog in catalogs for entry in catalog.plugins if entry["name"] == plugin]
    if len(matches) > 1:
        raise ValueError(f"{plugin} is in several marketplaces; use " +
                         " or ".join(f"{plugin}@{catalog.name}" for catalog, _ in matches))
    return matches[0] if matches else None


def materialize(catalog: Marketplace, entry: dict, workspace: Path, progress=None) -> Path:
    """The folder holding an entry's files, cloning it into ``workspace`` when remote."""
    from .plugin_install import clone, selected_directory
    source = entry["source"]
    if isinstance(source, dict) and source.get("source") == "local":
        source = source.get("path", "")
    if isinstance(source, str):
        relative = (Path(catalog.plugin_root) / source).as_posix() if catalog.plugin_root else source
        return selected_directory(catalog.root, relative)
    if not isinstance(source, dict):
        raise ValueError(f"{entry['name']}: unsupported plugin source")
    kind = source.get("source")
    if kind == "github":
        address = source.get("repo", "")
    elif kind in ("url", "git-subdir"):
        address = source.get("url", source.get("repo", ""))
    else:
        raise ValueError(f"{entry['name']}: {kind} plugin sources are not supported; "
                         "Eirene installs from git repositories and folders")
    ref, sha = source.get("ref") or "", source.get("sha") or ""
    if not isinstance(address, str) or not isinstance(ref, str) or not isinstance(sha, str) \
            or (ref and not re.fullmatch(_REF, ref)) or (sha and not re.fullmatch(_SHA, sha)):
        raise ValueError(f"{entry['name']}: invalid plugin source")
    checkout = workspace / "repo"
    clone(git_url(address), checkout, ref=ref, sha=sha, progress=progress)
    subdirectory = source.get("path") or "."
    return selected_directory(checkout, subdirectory) if subdirectory != "." else checkout


