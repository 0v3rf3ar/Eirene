#!/usr/bin/env python3
"""Set up the venv, run the tests, build the binary."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / (".venv-build-" + platform.system().lower() + "-" + platform.machine().lower())
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
    python = venv_python()
    if not python.exists():
        print(f"creating {VENV}", flush=True)
        if run([sys.executable, "-m", "venv", str(VENV)]) != 0:
            fail("could not create the virtualenv")
    if run([python, "-m", "pip", "install", "-q", "--upgrade", "pip"]) != 0:
        print("warning: could not upgrade pip", flush=True)
    if run([python, "-m", "pip", "install", "-q", "-r",
            str(ROOT / "requirements-dev.txt")]) != 0:
        fail("could not install the dependencies")
    return python


def test(python: Path) -> None:
    print("\nrunning the tests", flush=True)
    if run([python, "-m", "pytest", "-q"]) != 0:
        fail("tests failed - not building")
    print("tests passed", flush=True)


def freeze(python: Path, dist: Path | None = None, work: Path | None = None) -> Path:
    dist = dist or DIST
    work = work or WORK
    shutil.rmtree(work, ignore_errors=True)
    dist.mkdir(parents=True, exist_ok=True)
    print("\nbuilding the binary", flush=True)
    code = run([python, "-m", "PyInstaller", "--noconfirm", "--clean",
                "--log-level", "WARN", "--distpath", str(dist),
                "--workpath", str(work), str(SPEC)])
    if code != 0:
        fail("pyinstaller failed")
    binary = dist / ("eirene.exe" if os.name == "nt" else "eirene")
    if not binary.exists():
        fail(f"expected {binary} but it is not there")
    return binary


def smoke(binary: Path) -> None:
    print("\nchecking the binary", flush=True)
    for argv in ([binary, "--version"], [binary, "--help"]):
        result = subprocess.run([str(part) for part in argv], capture_output=True,
                                text=True, timeout=180, stdin=subprocess.DEVNULL)
        if result.returncode != 0:
            fail(f"{' '.join(str(p) for p in argv)} exited {result.returncode}\n"
                 f"{result.stderr[:500]}")
    print("binary responds to --version and --help", flush=True)


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

    if sys.version_info < (3, 10):
        fail("Python 3.10 or newer is required")
    print(f"eirene build on {platform.system()} {platform.machine()} "
          f"with python {platform.python_version()}", flush=True)
    python = Path(sys.executable) if args.no_install else ensure_venv()

    if not args.skip_tests:
        test(python)
    if args.test_only:
        return 0

    binary = freeze(python, args.dist_dir.expanduser().resolve(), args.work_dir.expanduser().resolve())
    smoke(binary)
    size = binary.stat().st_size / 1_000_000
    print(f"\n{binary} ({size:.1f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
