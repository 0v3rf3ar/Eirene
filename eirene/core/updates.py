"""GitHub release checks and verified, staged executable updates."""

from __future__ import annotations

import asyncio
import hashlib
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import httpx
from packaging.version import InvalidVersion, Version

from .. import __version__
from . import paths

REPOSITORY = "0v3rf3ar/Eirene"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_BINARY = 800 * 1024 * 1024


class UpdateError(Exception):
    """An update cannot safely proceed."""


@dataclass(frozen=True)
class Release:
    tag: str
    version: str
    assets: dict[str, str]


def _asset_url(url: str, tag: str) -> str:
    prefix = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    if not url.startswith(prefix) or "/" in url[len(prefix):] or "?" in url or "#" in url:
        raise UpdateError("release contains an unexpected download URL")
    return url


async def check(client: httpx.AsyncClient | None = None, *, current: str = __version__) -> Release | None:
    """Return a newer stable release; prereleases and drafts never replace it."""
    if client is None:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as owned:
            return await check(owned, current=current)
    try:
        response = await client.get(API_URL, headers={"Accept": "application/vnd.github+json"})
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise UpdateError("invalid release metadata")
        tag = body.get("tag_name", "")
        if not isinstance(tag, str) or not re.fullmatch(r"v?\d+\.\d+\.\d+[A-Za-z0-9.+-]*", tag):
            raise UpdateError("release has an invalid version tag")
        version = Version(tag.removeprefix("v"))
        if body.get("draft") or body.get("prerelease") or version.is_prerelease or version <= Version(current):
            return None
        assets = {}
        for item in body.get("assets", []):
            if isinstance(item, dict) and isinstance(item.get("name"), str) and isinstance(item.get("browser_download_url"), str):
                assets[item["name"]] = _asset_url(item["browser_download_url"], tag)
        return Release(tag, tag.removeprefix("v"), assets)
    except (httpx.HTTPError, InvalidVersion, ValueError, TypeError) as exc:
        raise UpdateError(f"could not check GitHub releases: {exc}") from exc


def asset_name(version: str, *, system: str | None = None, machine: str | None = None) -> str:
    host = system or platform.system()
    arch = (machine or platform.machine()).lower()
    target = {
        ("Linux", "x86_64"): "Linux-amd64", ("Linux", "amd64"): "Linux-amd64",
        ("Linux", "aarch64"): "Linux-arm64", ("Linux", "arm64"): "Linux-arm64",
        ("Darwin", "arm64"): "MacOS-silicon", ("Darwin", "aarch64"): "MacOS-silicon",
        ("Windows", "amd64"): "Windows-amd64", ("Windows", "x86_64"): "Windows-amd64",
    }.get((host, arch))
    if target is None:
        raise UpdateError(f"no release binary supports {host} {arch}")
    extension = "zip" if host == "Windows" else "tar.gz"
    return f"eirene-{target}-{version}.{extension}"


async def _download(client: httpx.AsyncClient, url: str, destination: Path, limit: int,
                    progress: Callable[[int, int], None] | None = None) -> None:
    async with client.stream("GET", url) as response:
        response.raise_for_status()
        total = int(response.headers.get("content-length", 0))
        if total > limit:
            raise UpdateError("release download exceeds the size limit")
        count = 0
        with destination.open("wb") as output:
            async for chunk in response.aiter_bytes(64 * 1024):
                count += len(chunk)
                if count > limit:
                    raise UpdateError("release download exceeds the size limit")
                output.write(chunk)
                if progress:
                    progress(count, total)


def _checksum(manifest: str, name: str) -> str:
    for line in manifest.splitlines():
        match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?(.+)", line.strip())
        if match and match[2] == name:
            return match[1].lower()
    raise UpdateError(f"release checksum is missing for {name}")


def _extract(archive: Path, destination: Path, windows: bool) -> None:
    """Copy just the expected regular binary; never extract archive paths."""
    name = "eirene.exe" if windows else "eirene"
    if windows:
        with zipfile.ZipFile(archive) as bundle:
            matches = [item for item in bundle.infolist() if item.filename == name]
            if len(matches) != 1 or matches[0].is_dir() or matches[0].file_size > MAX_BINARY:
                raise UpdateError("release archive has no unique bounded executable")
            mode = matches[0].external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateError("release executable is a symlink")
            with bundle.open(matches[0]) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    else:
        with tarfile.open(archive, "r:gz") as tar_bundle:
            matches_tar = [item for item in tar_bundle.getmembers() if item.name == name]
            if len(matches_tar) != 1 or not matches_tar[0].isfile() or matches_tar[0].size > MAX_BINARY:
                raise UpdateError("release archive has no unique bounded executable")
            source_tar = tar_bundle.extractfile(matches_tar[0])
            if source_tar is None:
                raise UpdateError("cannot read release executable")
            with source_tar, destination.open("wb") as target:
                shutil.copyfileobj(source_tar, target)
    destination.chmod(0o755)


def _smoke_test(binary: Path, version: str) -> None:
    result = subprocess.run([str(binary), "--version"], capture_output=True, timeout=30,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode or result.stdout.strip() != f"eirene {version}":
        raise UpdateError("downloaded executable failed its version smoke test")


async def download(release: Release, *, client: httpx.AsyncClient | None = None,
                   progress: Callable[[int, int], None] | None = None) -> Path:
    """Verify an archive and smoke-test its binary before offering installation."""
    name = asset_name(release.version)
    if name not in release.assets or "SHA256SUMS" not in release.assets:
        raise UpdateError("release is missing the platform archive or SHA256SUMS")
    if client is None:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as owned:
            async with asyncio.timeout(600):
                return await download(release, client=owned, progress=progress)
    directory = paths.home() / "updates"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        with tempfile.TemporaryDirectory(prefix="download-", dir=directory) as temporary:
            root = Path(temporary)
            archive, manifest = root / name, root / "SHA256SUMS"
            await _download(client, _asset_url(release.assets["SHA256SUMS"], release.tag), manifest, 64 * 1024)
            await _download(client, _asset_url(release.assets[name], release.tag), archive, MAX_DOWNLOAD, progress)
            expected = _checksum(manifest.read_text(encoding="ascii"), name)
            with archive.open("rb") as source:
                actual = hashlib.file_digest(source, "sha256").hexdigest()
            if actual != expected:
                raise UpdateError("release checksum mismatch; existing installation was not changed")
            windows = name.endswith(".zip")
            binary = root / ("eirene.exe" if windows else "eirene")
            await asyncio.to_thread(_extract, archive, binary, windows)
            await asyncio.to_thread(_smoke_test, binary, release.version)
            staged = directory / f"eirene-{release.version}{'.exe' if windows else ''}"
            os.replace(binary, staged)
            return staged
    except (OSError, ValueError, httpx.HTTPError, tarfile.TarError, zipfile.BadZipFile,
            subprocess.SubprocessError, TimeoutError) as exc:
        raise UpdateError(f"could not download update: {exc}") from exc


def install(staged: Path) -> str:
    """Replace frozen binaries atomically; source runs only download a standalone binary."""
    if not getattr(sys, "frozen", False):
        return f"Downloaded and verified: {staged}. This is a source installation; use that standalone binary or update your checkout."
    target = Path(sys.executable).resolve()
    # Copy beside the executable so the final replacement stays on one filesystem.
    with tempfile.NamedTemporaryFile(prefix=".eirene-update-", suffix=target.suffix,
                                     dir=target.parent, delete=False) as output:
        pending = Path(output.name)
    try:
        shutil.copyfile(staged, pending)
        pending.chmod(target.stat().st_mode & 0o777)
        if os.name != "nt":
            os.replace(pending, target)
            return "Update installed. Exit and restart Eirene to use the new version."
        return _windows_install(pending, target)
    except BaseException:
        pending.unlink(missing_ok=True)
        raise


def _windows_install(pending: Path, target: Path) -> str:
    """Wait for the running executable to unlock before replacement, preserving a backup."""
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    script = pending.with_suffix(".ps1")
    backup = target.with_suffix(".previous.exe")
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"Wait-Process -Id {os.getpid()} -Timeout 3600 -ErrorAction SilentlyContinue\n"
        f"if (Get-Process -Id {os.getpid()} -ErrorAction SilentlyContinue) {{ exit 1 }}\n"
        f"$target = {quote(target)}\n$pending = {quote(pending)}\n$backup = {quote(backup)}\n"
        "try {\n  Copy-Item -LiteralPath $target -Destination $backup -Force\n"
        "  $replaced = $false\n"
        "  for ($attempt = 0; $attempt -lt 30; $attempt++) {\n"
        "    try { Move-Item -LiteralPath $pending -Destination $target -Force; $replaced = $true; break }\n"
        "    catch { Start-Sleep -Seconds 1 }\n"
        "  }\n"
        "  if (-not $replaced) { throw 'Executable remains locked; retry the update after closing other Eirene processes.' }\n"
        "} catch {\n  if (Test-Path -LiteralPath $backup) { Copy-Item -LiteralPath $backup -Destination $target -Force }\n"
        "  $_ | Out-File -LiteralPath ($pending + '.error.txt')\n"
        "} finally { Remove-Item -LiteralPath $PSCommandPath -Force }\n", encoding="utf-8")
    try:
        subprocess.Popen(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", str(script)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=0x00000008 | 0x00000200)
    except OSError:
        script.unlink(missing_ok=True)
        raise
    return "Update verified and scheduled. Exit Eirene, then restart after the executable is replaced."
