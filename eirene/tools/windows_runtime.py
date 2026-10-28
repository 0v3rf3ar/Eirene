"""AppContainer adapter for the command supervisor, with fail-closed ACL grants.

The first runtime supports bounded stdin and streams output from private files.
Commands are serialized per user/session while temporary host ACLs are present.
Interactive streams, network grants and PTYs are deliberately rejected.
"""
from __future__ import annotations

import asyncio
import ctypes as C
import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

from ..core import paths
from ..core.errors import ToolError
from .windows_appcontainer import AppContainer, BOOL, DWORD, PTR, WSTR


def _check_tree(path):
    """Do not propagate a new package grant through a junction or symlink."""
    candidates = [path]
    if path.is_dir():
        def fail(error):
            raise error
        for directory, dirs, files in os.walk(path, followlinks=False, onerror=fail):
            candidates.extend(Path(directory) / name for name in [*dirs, *files])
    for candidate in candidates:
        attrs = candidate.lstat()
        if stat.S_ISLNK(attrs.st_mode) or getattr(attrs, "st_file_attributes", 0) & 0x400:
            raise ToolError(f"Windows sandbox grants do not support reparse points: {candidate}")


class Owner:
    def __init__(self):
        self.box = AppContainer()
        self.api = self.box._api
        self.grants = []
        self.files = []
        self.semaphore = None
        self.acquired = False
        self.native = None

    def acquire(self):
        kernel = self.api.kernel
        create = kernel.CreateSemaphoreW
        create.restype = PTR
        create.argtypes = [PTR, C.c_int32, C.c_int32, WSTR]
        self.release_semaphore = kernel.ReleaseSemaphore
        self.release_semaphore.restype = BOOL
        self.release_semaphore.argtypes = [PTR, C.c_int32, PTR]
        suffix = hashlib.sha256(str(Path.home()).casefold().encode()).hexdigest()[:24]
        self.semaphore = create(None, 1, 1, "Local\\Eirene.CommandSandbox." + suffix)
        self.api.check(self.semaphore, "CreateSemaphoreW")
        status = self.api.wait_object(self.semaphore, 0)
        if status == 258:
            raise ToolError("A sandboxed Windows command is already running; poll or stop it before starting another")
        self.api.check(status == 0, "WaitForSingleObject(command slot)")
        self.acquired = True

    def sid(self):
        text = PTR()
        self.api.check(self.api.sid_text(self.box._sid, C.byref(text)), "ConvertSidToStringSidW")
        try:
            return "*" + C.wstring_at(text)
        finally:
            self.api.local_free(text)

    def acl(self, path, *arguments):
        executable = str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe")
        try:
            result = subprocess.run([executable, str(path), *arguments, "/L", "/Q"],
                                    capture_output=True, timeout=30, creationflags=0x08000000)
        except subprocess.TimeoutExpired as exc:
            raise ToolError(f"Windows sandbox ACL operation timed out: {path}") from exc
        if result.returncode:
            raise ToolError(f"Windows sandbox cannot update ACL for {path}: "
                            + result.stderr.decode(errors="replace")[:1000])

    def grant(self, path, writable):
        path = Path(path).resolve(strict=True)
        if path == Path(path.anchor) or str(path).startswith("\\\\"):
            raise ToolError("Windows sandbox grants require a specific local path, not a volume root or network share")
        _check_tree(path)
        sid = self.sid()
        permissions = ("(OI)(CI)" if path.is_dir() else "") + ("M" if writable else "RX")
        # Record before mutation: a failed icacls operation may be partial.
        self.grants.append((path, sid))
        self.acl(path, "/grant", f"{sid}:{permissions}")

    def close(self):
        try:
            if self.native:
                self.native.close()
            for file in self.files:
                file.close()
            while self.grants:
                path, sid = self.grants[-1]
                if path.exists():
                    self.acl(path, "/remove:g", sid)
                self.grants.pop()
            self.box.close()
        finally:
            # Never allow another grant operation while an old command survives.
            if self.native is None or self.native.closed:
                if self.acquired:
                    self.api.check(self.release_semaphore(self.semaphore, 1, None), "ReleaseSemaphore")
                    self.acquired = False
                if self.semaphore:
                    self.api.close_handle(self.semaphore)
                    self.semaphore = None


class AsyncProcess:
    """Small asyncio subprocess interface consumed by tools.processes."""
    def __init__(self, owner, output):
        self.owner = owner
        self.native = owner.native
        self.pid = self.native.pid
        self.returncode = None
        self.stdin = None  # Bounded input was supplied before process creation.
        self.stderr = None
        self.stdout = asyncio.StreamReader()
        self._eirene_job = self.native._job
        self._output = output
        self._task = asyncio.create_task(self._pump())

    async def _pump(self):
        try:
            while True:
                chunk = self._output.read(8192)
                if chunk:
                    self.stdout.feed_data(chunk)
                    await asyncio.sleep(0)
                    continue
                try:
                    self.returncode = self.native.wait(0)
                except TimeoutError:
                    await asyncio.sleep(0.02)
                    continue
                # Drain bytes written just before the process exit signal.
                while chunk := self._output.read(8192):
                    self.stdout.feed_data(chunk)
                    await asyncio.sleep(0)
                self.stdout.feed_eof()
                return self.returncode
        except Exception as exc:
            self.stdout.set_exception(exc)
            raise

    async def wait(self):
        return await asyncio.shield(self._task)

    def kill(self):
        self._eirene_job.terminate()

    def release(self):
        self.owner.close()
        self._eirene_job = None


async def start(argv, root, cwd, *, network=False, read_paths=(), write_paths=(),
                read_only=False, env=None, input_text=None):
    if os.name != "nt":
        raise ToolError("Windows AppContainer runtime requires Windows")
    if network:
        raise ToolError("Windows AppContainer network grants are not supported; no host fallback")
    if read_only and write_paths:
        raise ToolError("read-only execution cannot grant writable paths")
    root = Path(root).resolve(strict=True)
    cwd = Path(cwd).resolve(strict=True)
    reads = [(root / Path(p).expanduser()).resolve(strict=True) for p in read_paths]
    writes = [(root / Path(p).expanduser()).resolve(strict=True) for p in write_paths]
    if not any(cwd == path or path in cwd.parents for path in [root, *reads, *writes]):
        raise ToolError("Windows command working directory leaves its grants")
    executable = shutil.which(argv[0])
    if not executable:
        raise ToolError(f"Windows command executable is unavailable: {argv[0]}")
    argv = [executable, *argv[1:]]
    owner = Owner()
    try:
        owner.acquire()
        for path, writable in [(root, not read_only), *((p, False) for p in reads),
                               *((p, True) for p in writes)]:
            owner.grant(path, writable)
        temp = None if read_only else paths.temp_dir()
        if temp:
            owner.grant(temp, True)
        runtime = Path(executable).resolve().parent
        system_dirs = [Path(os.environ[key]).resolve() for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")
                       if os.environ.get(key)]
        if not any(runtime == path or path in runtime.parents for path in [root, *reads, *writes, *system_dirs]):
            owner.grant(runtime, False)
        stdin = (owner.box.home / "stdin.bin").open("w+b")
        owner.files.append(stdin)
        stdin.write((input_text or "").encode("utf-8"))
        stdin.seek(0)
        stdout = (owner.box.home / "stdout.bin").open("w+b")
        owner.files.append(stdout)
        output = (owner.box.home / "stdout.bin").open("rb")
        owner.files.append(output)
        import msvcrt
        handles = (msvcrt.get_osfhandle(stdin.fileno()), msvcrt.get_osfhandle(stdout.fileno()))
        try:
            for handle in handles:
                os.set_handle_inheritable(handle, True)
            owner.native = owner.box.spawn(argv, cwd=cwd,
                env={"PATH": os.environ.get("PATH", ""), **(env or {})},
                std_handles=(handles[0], handles[1], handles[1]), temp=temp)
        finally:
            for handle in handles:
                os.set_handle_inheritable(handle, False)
        return AsyncProcess(owner, output)
    except BaseException:
        owner.close()
        raise
