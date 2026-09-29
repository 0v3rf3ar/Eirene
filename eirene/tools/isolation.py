"""Fail-closed execution environments with explicit host mounts."""
from __future__ import annotations

import os
import json
import shutil
import sys
import tempfile
from pathlib import Path

from ..core.errors import ToolError


def command(command: str, root: Path, *, backend: str = "auto",
            network: bool = False, read_paths=(), write_paths=(),
            read_only: bool = False) -> list[str]:
    from .shell import posix_argv
    root = root.resolve()
    if backend == "auto":
        backend = "seatbelt" if sys.platform == "darwin" else "bubblewrap"
    if backend == "none":
        if read_only:
            raise ToolError("read-only execution requires an isolation backend")
        return posix_argv(command)
    reads = [(root / Path(p).expanduser()).resolve() for p in read_paths]
    writes = [(root / Path(p).expanduser()).resolve() for p in write_paths]
    if read_only and writes:
        raise ToolError("read-only execution cannot grant writable paths")
    for path in reads + writes:
        if not path.exists():
            raise ToolError(f"mount path does not exist: {path}; request its existing parent")
        if path == Path("/"):
            raise ToolError("grant a specific directory, not the filesystem root")
    mounts = [(root, not read_only), *((p, False) for p in reads),
              *((p, True) for p in writes)]
    # Parent mounts must precede children; otherwise a parent hides the child.
    mounts.sort(key=lambda item: len(item[0].parts))
    if backend == "seatbelt":
        exe = shutil.which("sandbox-exec")
        if sys.platform != "darwin" or not exe:
            raise ToolError("macOS isolation needs sandbox-exec; no unsandboxed fallback")
        profile = ["(version 1)", "(deny default)", "(allow process*)",
                   "(allow sysctl-read)", "(allow mach-lookup)",
                   '(allow file-read-metadata)',
                   '(allow file-read* (subpath "/System") (subpath "/usr") (subpath "/bin") (subpath "/sbin") (subpath "/Library") (subpath "/private/etc") (subpath "/dev"))',
                   '(allow file-write* (literal "/dev/null") (literal "/dev/tty"))']
        scratch = _mac_scratch()
        mounts.append((scratch, True))
        if Path("/opt/homebrew").is_dir():
            mounts.append((Path("/opt/homebrew"), False))
        for path, writable in mounts:
            rule = "subpath" if path.is_dir() else "literal"
            quoted = json.dumps(str(path), ensure_ascii=False)
            profile.append(f"(allow file-read* ({rule} {quoted}))")
            if writable:
                profile.append(f"(allow file-write* ({rule} {quoted}))")
        if network:
            profile.append("(allow network*)")
        return [exe, "-p", "\n".join(profile), *posix_argv(command)]
    if backend == "bubblewrap":
        exe = shutil.which("bwrap")
        if sys.platform != "linux" or not exe:
            raise ToolError("Bubblewrap isolation requires Linux and bwrap; no unsandboxed fallback")
        argv = [exe, "--die-with-parent", "--new-session", "--unshare-all",
                "--cap-drop", "ALL"]
        if network:
            argv += ["--share-net"]
        for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64",
                     "/etc/ssl", "/etc/pki", "/etc/crypto-policies", "/etc/ld.so.cache", "/etc/alternatives",
                     "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf",
                     "/etc/passwd", "/etc/group", "/etc/localtime"):
            if Path(name).exists():
                argv += ["--ro-bind", name, name]
        argv += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/tmp/eirene-home"]
        for path, writable in mounts:
            argv += ["--bind" if writable else "--ro-bind", str(path), str(path)]
        argv += ["--setenv", "HOME", "/tmp/eirene-home",
                 "--setenv", "TMPDIR", "/tmp", "--chdir", str(root)]
        return argv + posix_argv(command)
    raise ToolError(f"unknown isolation backend: {backend}")


def environment(extra=None) -> dict[str, str]:
    """Keep credentials, loader overrides and desktop sockets out of children."""
    allowed = {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR"}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    if sys.platform == "darwin":
        scratch = str(_mac_scratch())
        env.update({"HOME": scratch, "TMPDIR": scratch})
    else:
        env.update({"HOME": "/tmp/eirene-home", "TMPDIR": "/tmp"})
    if extra:
        env.update(extra)
    return env


def _mac_scratch() -> Path:
    """Private temporary storage for sandboxed tools and caches."""
    path = Path(tempfile.gettempdir()) / f"eirene-sandbox-{os.getuid()}"
    path.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ToolError("unsafe macOS sandbox temporary directory")
    path.chmod(0o700)
    return path.resolve()
