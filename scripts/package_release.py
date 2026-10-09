#!/usr/bin/env python3
"""Create compressed, executable release archives with a portable layout."""
from __future__ import annotations

import argparse
import os
import platform
import stat
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = {
    "linux-amd64": ("Linux", {"x86_64", "amd64"}),
    "linux-arm64": ("Linux", {"aarch64", "arm64"}),
    "macos-silicon": ("Darwin", {"arm64", "aarch64"}),
    "windows-amd64": ("Windows", {"amd64", "x86_64"}),
}


def check_host(target: str) -> None:
    system, machines = TARGETS[target]
    if platform.system() != system or platform.machine().lower() not in machines:
        raise SystemExit(f"{target} needs a native {system} runner ({sorted(machines)}); "
                         f"got {platform.system()} {platform.machine()}")


def package(target: str, binary: Path, output: Path, version: str) -> Path:
    """Archive the executable plus license files; preserve executable mode."""
    if not binary.is_file() or binary.is_symlink():
        raise ValueError("release binary must be a regular file")
    windows = target == "windows-amd64"
    name = "eirene.exe" if windows else "eirene"
    files = [(binary, name), (ROOT / "LICENSE", "LICENSE"), (ROOT / "NOTICE", "NOTICE")]
    output.mkdir(parents=True, exist_ok=True)
    label = target.replace("linux-", "Linux-").replace("macos-", "MacOS-").replace("windows-", "Windows-")
    archive = output / f"eirene-{label}-{version}.{'zip' if windows else 'tar.gz'}"
    if windows:
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
            for source, member in files:
                info = zipfile.ZipInfo(member)
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | (0o755 if member == name else 0o644)) << 16
                bundle.writestr(info, source.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    else:
        with tarfile.open(archive, "w:gz", compresslevel=9) as bundle:
            for source, member in files:
                info = bundle.gettarinfo(str(source), arcname=member)
                info.mode = 0o755 if member == name else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with source.open("rb") as data:
                    bundle.addfile(info, data)
    return archive


def smoke_archive(archive: Path, windows: bool) -> None:
    """Execute the extracted release, not just the original dist binary."""
    import subprocess
    with tempfile.TemporaryDirectory(prefix="eirene-release-") as temporary:
        root = Path(temporary)
        name = "eirene.exe" if windows else "eirene"
        if windows:
            with zipfile.ZipFile(archive) as bundle:
                bundle.extractall(root)
        else:
            with tarfile.open(archive) as bundle:
                bundle.extractall(root, filter="data")
        binary = root / name
        if not windows and not os.access(binary, os.X_OK):
            raise SystemExit("archive lost the executable permission")
        for argument in ("--version", "--help"):
            subprocess.run([str(binary), argument], check=True, timeout=180,
                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--output", type=Path, default=ROOT / "release")
    args = parser.parse_args()
    check_host(args.target)
    binary = args.dist / ("eirene.exe" if args.target == "windows-amd64" else "eirene")
    from release_metadata import read_version
    version = read_version(ROOT / "pyproject.toml")
    archive = package(args.target, binary, args.output, version)
    smoke_archive(archive, args.target == "windows-amd64")
    print(archive)


if __name__ == "__main__":
    main()
