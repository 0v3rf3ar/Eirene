#!/usr/bin/env python3
"""Run LibreOffice headless with a private, throwaway profile.

  python soffice.py --headless --convert-to pdf deck.pptx [--outdir out/]

Arguments are passed to LibreOffice unchanged. The wrapper finds the program on
Linux, macOS and Windows, gives each run its own user profile (so a running
LibreOffice window or a stale lock cannot make it hang), adds --headless and
--norestore, stops it after --timeout seconds (default 180), and kills a conversion whose
output grows past SOFFICE_MAX_OUTPUT_MB (default 512), which means it is looping.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Largest amount a single conversion may write before it is treated as runaway.
MAX_OUTPUT = int(os.environ.get("SOFFICE_MAX_OUTPUT_MB", "512")) * 1048576

CANDIDATES = [
    "soffice", "libreoffice",
    "/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice", "/opt/libreoffice/program/soffice",
    "/snap/bin/libreoffice", "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    r"C:\Program Files\LibreOffice\program\soffice.exe",
    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
]


def find() -> str:
    override = os.environ.get("SOFFICE")
    if override:
        return override
    for name in CANDIDATES:
        path = shutil.which(name) or (name if os.path.isfile(name) else None)
        if path:
            return path
    raise SystemExit("LibreOffice was not found. Install it (https://www.libreoffice.org) "
                     "or set SOFFICE to the soffice executable.")


def outdir_of(args: list[str]) -> Path | None:
    if "--outdir" in args and args.index("--outdir") + 1 < len(args):
        return Path(args[args.index("--outdir") + 1])
    return Path.cwd() if "--convert-to" in args else None


def folder_size(folder: Path) -> int:
    try:
        return sum(p.stat().st_size for p in folder.iterdir() if p.is_file())
    except OSError:
        return 0


def stop(process: subprocess.Popen) -> None:
    """Kill LibreOffice's whole process tree; the launcher alone leaves soffice.bin running."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        process.kill()
    try:
        process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run(args: list[str], timeout: float = 180, profile: Path | None = None) -> subprocess.CompletedProcess:
    """Run soffice with args; a temporary profile is used unless one is given."""
    owned = profile is None
    profile = Path(tempfile.mkdtemp(prefix="soffice-profile-")) if owned else profile
    try:
        command = [find(), f"-env:UserInstallation={profile.resolve().as_uri()}"]
        for flag in ("--headless", "--norestore", "--nologo", "--nodefault", "--nolockcheck"):
            if flag not in args:
                command.append(flag)
        command += args
        env = dict(os.environ)
        env.setdefault("SAL_USE_VCLPLUGIN", "svp")  # no display needed
        watched = outdir_of(args)
        before = folder_size(watched) if watched else 0
        existing = {e.name for e in watched.iterdir()} if watched and watched.is_dir() else set()
        group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
                 else {"start_new_session": True})
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                   stdin=subprocess.DEVNULL, env=env, **group)
        deadline = time.monotonic() + timeout
        while True:
            try:
                out, err = process.communicate(timeout=0.5)
                return subprocess.CompletedProcess(command, process.returncode, out, err)
            except subprocess.TimeoutExpired:
                pass
            # Some conversions loop and keep writing (for example the text export of
            # certain tables); stop them before they fill the disk.
            if watched and folder_size(watched) - before > MAX_OUTPUT:
                stop(process)
                for entry in watched.iterdir():
                    if entry.name not in existing and entry.is_file():
                        entry.unlink(missing_ok=True)  # the partial, oversized output
                raise SystemExit(f"LibreOffice was stopped: its output passed {MAX_OUTPUT // 1048576} MB, "
                                 "so the conversion was looping. Use another route for this format.")
            if time.monotonic() > deadline:
                stop(process)
                raise SystemExit(f"LibreOffice did not finish within {timeout:g}s")
    finally:
        if owned:
            shutil.rmtree(profile, ignore_errors=True)


def convert(path: str | Path, fmt: str, outdir: str | Path | None = None, timeout: float = 180) -> Path:
    """Convert a file with LibreOffice and return the output path."""
    path = Path(path).resolve()
    outdir = Path(outdir or path.parent).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    result = run(["--convert-to", fmt, "--outdir", str(outdir), str(path)], timeout=timeout)
    target = outdir / f"{path.stem}.{fmt.split(':', 1)[0]}"
    if result.returncode or not target.exists():
        detail = (result.stderr or result.stdout).strip()
        raise SystemExit(f"conversion failed: {detail or 'no output file was written'}")
    return target


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    timeout = 180.0
    if "--timeout" in args:
        index = args.index("--timeout")
        timeout = float(args[index + 1])
        del args[index:index + 2]
    result = run(args, timeout=timeout)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
