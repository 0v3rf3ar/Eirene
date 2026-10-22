#!/usr/bin/env python3
"""Sync the uv environment, run the tests, build the binary."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = Path(os.environ.get("UV_PROJECT_ENVIRONMENT", ROOT / ".venv"))
if not VENV.is_absolute():
    VENV = ROOT / VENV
SPEC = ROOT / "build" / "eirene.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "work"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(argv: list[str], **kwargs) -> int:
    print(f"» {' '.join(str(part) for part in argv)}", flush=True)
    return subprocess.call([str(part) for part in argv], cwd=str(ROOT), **kwargs)


def ensure_venv() -> Path:
    uv = shutil.which("uv")
    if not uv:
        fail("uv is required; install it from https://docs.astral.sh/uv/getting-started/installation/")
    if run([uv, "sync", "--locked", "--group", "build", "--python", sys.executable]) != 0:
        fail("could not sync the dependencies")
    return venv_python()


def test(python: Path) -> None:
    print("\nrunning the tests", flush=True)
    if run([python, "-m", "pytest", "-q"]) != 0:
        fail("tests failed - not building")
    print("tests passed", flush=True)


def freeze(python: Path, dist: Path | None = None, work: Path | None = None) -> Path:
    dist = dist or DIST
    work = work or WORK
    dist.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    print("\nbuilding the binary", flush=True)
    name = "eirene.exe" if os.name == "nt" else "eirene"
    # Build away from the published path. Failed builds and smoke checks leave
    # the old executable intact; parallel builds get independent work folders.
    with tempfile.TemporaryDirectory(prefix=".eirene-build-", dir=dist) as staging, \
            tempfile.TemporaryDirectory(prefix="eirene-", dir=work) as scratch:
        code = run([python, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--log-level", "WARN", "--distpath", staging,
                    "--workpath", scratch, str(SPEC)])
        if code != 0:
            fail("pyinstaller failed; existing executable was not changed")
        built = Path(staging) / name
        if not built.exists():
            fail(f"expected {built} but it is not there")
        smoke(built)
        binary = dist / name
        os.replace(built, binary)
    return binary


def smoke(binary: Path) -> None:
    print("\nchecking the binary", flush=True)
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(binary)).open_embedded_archive("PYZ.pyz")
    for name in archive.toc:
        archive.extract(name)
    print(f"verified {len(archive.toc)} bundled Python modules", flush=True)
    for argv in ([binary, "--version"], [binary, "--help"]):
        result = subprocess.run([str(part) for part in argv], capture_output=True,
                                text=True, timeout=180, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            fail(f"{' '.join(str(p) for p in argv)} exited {result.returncode}\n"
                 f"{result.stderr[:500]}")
    print("binary responds to --version and --help", flush=True)
    if os.name != "nt":
        # This must launch the frozen executable: source-only UI tests cannot
        # detect missing or corrupted lazy-import archive entries.
        if run([sys.executable, ROOT / "scripts" / "smoke_binary_ui.py", binary]) != 0:
            fail("frozen popup smoke test failed; existing executable was not changed")


def fail(message: str) -> None:
    print(f"\nerror: {message}", file=sys.stderr, flush=True)
    raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build eirene.")
    parser.add_argument("--test-only", action="store_true",
                        help="run the tests and stop")
    parser.add_argument("--skip-tests", action="store_true",
                        help="build without running the tests")
    parser.add_argument("--no-install", action="store_true",
                        help="use this Python environment without downloading dependencies")
    parser.add_argument("--dist-dir", type=Path, default=DIST,
                        help="output directory (default: dist)")
    parser.add_argument("--work-dir", type=Path, default=WORK,
                        help="temporary packaging directory (default: build/work)")
    args = parser.parse_args()

    if sys.version_info < (3, 11):
        fail("Python 3.11 or newer is required")
    print(f"eirene build on {platform.system()} {platform.machine()} "
          f"with python {platform.python_version()}", flush=True)
    if not args.no_install:
        python = ensure_venv()
        # Packaging and its smoke checks must run in the same synced environment.
        return run([python, ROOT / "build.py", "--no-install", *sys.argv[1:]])
    python = Path(sys.executable)

    if not args.skip_tests:
        test(python)
    if args.test_only:
        return 0

    binary = freeze(python, args.dist_dir.expanduser().resolve(), args.work_dir.expanduser().resolve())
    size = binary.stat().st_size / 1_000_000
    print(f"\n{binary} ({size:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
