"""Run an edit on either an unpacked folder or a packed Office file."""

from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path

from package import pack, unpack


@contextmanager
def opened(source: str | Path, output: str | Path | None = None, *, write: bool = True):
    """Yield a folder to edit. For a packed file, repack to output (default: in place).

    With write=False the folder is only read and nothing is repacked.
    """
    source = Path(source)
    if source.is_dir():
        if output:
            raise SystemExit("-o applies only when the input is a packed file")
        yield source
        return
    if not source.exists():
        raise SystemExit(f"{source} does not exist")
    temporary = Path(tempfile.mkdtemp(prefix="office-edit-"))
    try:
        folder = unpack(source, temporary / "unpacked")
        yield folder
        if write:
            pack(folder, Path(output) if output else source)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
