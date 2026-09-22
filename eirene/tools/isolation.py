"""Fail-closed execution environments with explicit host mounts."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from ..core.errors import ToolError


def command(command: str, root: Path, *, backend: str = "auto",
            network: bool = False, read_paths=(), write_paths=(),
            read_only: bool = False) -> list[str]:
    root = root.resolve()
    if backend == "auto":
        backend = "bubblewrap"
    if backend == "none":
        if read_only:
            raise ToolError("read-only execution requires an isolation backend")
        return ["/bin/sh", "-c", command]
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
    if backend == "bubblewrap":
        exe = shutil.which("bwrap")
        if sys.platform != "linux" or not exe:
            raise ToolError("Bubblewrap isolation requires Linux and bwrap; no unsandboxed fallback")
        argv = [exe, "--die-with-parent", "--new-session", "--unshare-all",
                "--cap-drop", "ALL"]
        if network:
            argv += ["--share-net"]
        for name in ("/usr", "/bin", "/sbin", "/lib", "/lib64",
                     "/etc/ssl", "/etc/pki", "/etc/ld.so.cache", "/etc/alternatives",
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
        return argv + ["/bin/sh", "-c", command]
    raise ToolError(f"unknown isolation backend: {backend}")


def environment(extra=None) -> dict[str, str]:
    """Keep credentials, loader overrides and desktop sockets out of children."""
    allowed = {"PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR"}
    env = {k: v for k, v in os.environ.items() if k in allowed}
    env.update({"HOME": "/tmp/eirene-home", "TMPDIR": "/tmp"})
    if extra:
        env.update(extra)
    return env
