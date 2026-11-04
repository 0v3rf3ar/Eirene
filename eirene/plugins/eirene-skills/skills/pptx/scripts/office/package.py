"""Unpack and pack Office files safely.

An Office file is a ZIP of XML parts. Files from other people are untrusted, so
unpacking refuses absolute paths, '..' segments and symbolic links. Packing writes
[Content_Types].xml first and stores entries in a stable order.
"""

from __future__ import annotations

import os
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

CONTENT_TYPES = "[Content_Types].xml"


def unpack(source: str | Path, target: str | Path) -> Path:
    source, target = Path(source), Path(target)
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty; choose a new folder")
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    with zipfile.ZipFile(source) as archive:
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in info.filename:
                raise SystemExit(f"refusing unsafe path in archive: {info.filename}")
            if stat.S_ISLNK(info.external_attr >> 16):
                continue  # never create symlinks from an untrusted archive
            destination = (root / Path(*name.parts)).resolve()
            if root not in destination.parents and destination != root:
                raise SystemExit(f"refusing path outside the folder: {info.filename}")
            if info.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, open(destination, "wb") as dst:
                dst.write(src.read())
    return target


def pack(folder: str | Path, output: str | Path) -> Path:
    folder, output = Path(folder), Path(output)
    if not (folder / CONTENT_TYPES).exists():
        raise SystemExit(f"{folder} has no {CONTENT_TYPES}; is it an unpacked Office file?")
    files = sorted(p for p in folder.rglob("*") if p.is_file() and not p.is_symlink())
    names = [p.relative_to(folder).as_posix() for p in files]
    order = sorted(names, key=lambda n: (n != CONTENT_TYPES, not n.startswith("_rels/"), n))
    temporary = output.with_name(output.name + ".tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in order:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, (folder / name).read_bytes())
    os.replace(temporary, output)
    return output


def read_parts(path: str | Path) -> dict[str, bytes]:
    """All parts of a packed file or an unpacked folder, by POSIX path."""
    path = Path(path)
    if path.is_dir():
        return {p.relative_to(path).as_posix(): p.read_bytes()
                for p in path.rglob("*") if p.is_file() and not p.is_symlink()}
    with zipfile.ZipFile(path) as archive:
        return {i.filename: archive.read(i) for i in archive.infolist() if not i.is_dir()}


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in ("unpack", "pack"):
        print("usage: python package.py unpack FILE FOLDER\n"
              "       python package.py pack FOLDER FILE")
        return 2
    if sys.argv[1] == "unpack":
        print(unpack(sys.argv[2], sys.argv[3]))
    else:
        print(pack(sys.argv[2], sys.argv[3]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
