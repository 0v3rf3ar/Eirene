"""Fail-closed execution environments with explicit host mounts."""
from __future__ import annotations

import os
import json
import shutil
import sys
from pathlib import Path

from ..core import paths
from ..core.errors import ToolError


def command(command: str, root: Path, *, backend: str = "auto",
            network: bool = False, read_paths=(), write_paths=(),
            read_only: bool = False, launch_argv: list[str] | None = None, workdir: Path | None = None,
            home_path: Path | None = None) -> list[str]:
    from .shell import posix_argv
    launch_argv = launch_argv or posix_argv(command)
    root = root.resolve()
    if backend == "auto":
        backend = "seatbelt" if sys.platform == "darwin" else "bubblewrap"
    if backend == "none":
        if read_only:
            raise ToolError("read-only execution requires an isolation backend")
        return launch_argv
    reads = [(root / Path(p).expanduser()).resolve() for p in read_paths]
    writes = [(root / Path(p).expanduser()).resolve() for p in write_paths]
    if home_path:
        home_path = home_path.resolve()
        if not any(home_path == mount or mount in home_path.parents for mount in [root, *writes]):
            raise ToolError('persistent tool home must be inside a granted writable directory')
    if read_only and writes:
        raise ToolError("read-only execution cannot grant writable paths")
    for path in reads + writes:
        if not path.exists():
            raise ToolError(f"mount path does not exist: {path}; request its existing parent")
        if path == Path("/"):
            raise ToolError("grant a specific directory, not the filesystem root")
    # A read grant inside a writable mount is already readable; binding it again
    # read-only after its parent would quietly make that part unwritable.
    writable = [*writes, *([] if read_only else [root])]
    reads = [p for p in reads if not any(p == w or w in p.parents for w in writable)]
    mounts = [(root, not read_only), *((p, False) for p in reads),
              *((p, True) for p in writes)]
    if not read_only:
        mounts.append((paths.temp_dir(), True))
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
        if read_only:
            mounts.append((_mac_scratch(), True))
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
        return [exe, "-p", "\n".join(profile), *launch_argv]
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
        argv += ["--setenv", "HOME", str(home_path) if home_path else "/tmp/eirene-home",
                 "--setenv", "TMPDIR", "/tmp" if read_only else str(paths.temp_dir()),
                 "--chdir", str(workdir or root)]
        return argv + launch_argv
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
    return paths.temp_dir()


# Persistent sysctl file the fixes below suggest; the installer uses the same.
USERNS_SYSCTL_FILE = "/etc/sysctl.d/90-eirene-userns.conf"


def _setting(path: str) -> str:
    try:
        return "".join(ch for ch in Path(path).read_text() if ch.isdigit())
    except OSError:
        return ""


def _in_container() -> bool:
    if Path("/.dockerenv").exists() or Path("/run/.containerenv").exists():
        return True
    tool = shutil.which("systemd-detect-virt")
    if not tool:
        return False
    import subprocess
    try:
        return subprocess.run([tool, "--container", "--quiet"], timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def bubblewrap_package_command() -> str:
    """How to install Bubblewrap on this distribution, or empty."""
    sudo = "" if hasattr(os, "geteuid") and os.geteuid() == 0 else "sudo "
    for tool, install in (("apt-get", "apt install bubblewrap"), ("dnf", "dnf install bubblewrap"),
                          ("yum", "yum install bubblewrap"), ("pacman", "pacman -S bubblewrap"),
                          ("zypper", "zypper install bubblewrap"), ("apk", "apk add bubblewrap"),
                          ("xbps-install", "xbps-install -S bubblewrap"),
                          ("emerge", "emerge sys-apps/bubblewrap")):
        if shutil.which(tool):
            return sudo + install
    return ""


def bubblewrap_problem() -> tuple[str, list[str]]:
    """Why Bubblewrap cannot isolate commands here, and how to fix it.

    ("", []) when it starts. Runs the same isolation Eirene uses, on a no-op,
    so a blocked namespace shows up here rather than on the first command.
    """
    exe = shutil.which("bwrap")
    if not exe:
        install = bubblewrap_package_command()
        return ("Bubblewrap is not installed.",
                [f"Install it: {install}" if install
                 else "Install your distribution's bubblewrap package."])
    import subprocess
    try:
        result = subprocess.run(
            [exe, "--die-with-parent", "--new-session", "--unshare-all", "--cap-drop", "ALL",
             "--ro-bind", "/", "/", "true"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            text=True, timeout=10)
    except subprocess.TimeoutExpired:
        return "Bubblewrap did not start within 10 seconds.", []
    except OSError as exc:
        return f"Bubblewrap could not run: {exc}", []
    if result.returncode == 0:
        return "", []
    error = (result.stderr or "").strip().splitlines()
    reason = (error[0].removeprefix("bwrap: ") if error else f"bwrap exited {result.returncode}")
    for setting, path, value in (
            ("kernel.unprivileged_userns_clone", "/proc/sys/kernel/unprivileged_userns_clone", "1"),
            ("user.max_user_namespaces", "/proc/sys/user/max_user_namespaces", "15000")):
        if _setting(path) == "0":
            return (f"User namespaces are turned off ({reason}).",
                    [f"Allow now: sudo sysctl -w {setting}={value}",
                     f"Keep it: echo {setting}={value} | sudo tee {USERNS_SYSCTL_FILE}"])
    if _setting("/proc/sys/kernel/apparmor_restrict_unprivileged_userns") == "1":
        setting = "kernel.apparmor_restrict_unprivileged_userns"
        return (f"AppArmor blocks user namespaces ({reason}).",
                [f"Allow now: sudo sysctl -w {setting}=0",
                 f"Keep it: echo {setting}=0 | sudo tee {USERNS_SYSCTL_FILE}",
                 "Or give bwrap its own AppArmor profile that allows userns."])
    if _in_container():
        return (f"This container forbids nested namespaces ({reason}).",
                ["Enable nesting (Proxmox LXC: features: nesting=1), or run Eirene on the host."])
    return (f"Bubblewrap failed: {reason}",
            ["Check that this kernel allows unprivileged user namespaces."])
