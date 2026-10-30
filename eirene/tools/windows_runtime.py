"""AppContainer adapter for the command supervisor, with persistent workspace grants.

Each workspace has its own persistent AppContainer profile (a separate read-only one
for read-only execution). Its file grants are made once and inherited by new files,
so commands start without rewriting ACLs and may run concurrently. Approved extra
paths are granted per command to a unique capability and revoked afterwards.
Network capabilities are added only for approved network access.
"""
from __future__ import annotations

import asyncio
import ctypes as C
import hashlib
import os
import shutil
import struct
import subprocess
import threading
import time
import uuid
from pathlib import Path

from ..core import paths
from ..core.errors import ToolError
from .windows_appcontainer import AppContainer, BOOL, DWORD, PTR, WSTR, _Win32


def _bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = list(args)
    return function


class _Dacl:
    """Adds one SID's ACE through SDDL text, leaving the other entries intact."""

    def __init__(self, api):
        self.api = api
        self.to_text = _bind(api.security, "ConvertSecurityDescriptorToStringSecurityDescriptorW", BOOL,
                             PTR, DWORD, DWORD, C.POINTER(PTR), PTR)
        self.from_text = _bind(api.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", BOOL,
                               WSTR, DWORD, C.POINTER(PTR), PTR)

    def text(self, descriptor):
        text = PTR()
        # DACL_SECURITY_INFORMATION=4, SDDL_REVISION_1=1.
        self.api.check(self.to_text(descriptor, 1, 4, C.byref(text), None),
                       "ConvertSecurityDescriptorToStringSecurityDescriptorW")
        try:
            return C.wstring_at(text)
        finally:
            self.api.local_free(text)

    def descriptor(self, sddl):
        descriptor = PTR()
        self.api.check(self.from_text(sddl, 1, C.byref(descriptor), None),
                       "ConvertStringSecurityDescriptorToSecurityDescriptorW")
        return descriptor

    def grant(self, target, sid, rights):
        self.write(target, self.read(target) + f"(A;;{rights:#x};;;{sid})")

    def has(self, target, sid):
        return f";;;{sid})" in self.read(target)


class _WindowObjects(_Dacl):
    """Lets the package SID initialise user32 outside the interactive window station.

    WinSta0 already admits ALL APPLICATION PACKAGES. SSH and service window stations
    do not, so PowerShell and other user32 programs die with STATUS_DLL_INIT_FAILED.
    Rights are narrower than WinSta0's: no clipboard, screen reads, hooks or journaling.
    """
    STATION, DESKTOP = 0x20123, 0x200C7

    def __init__(self, api):
        super().__init__(api)
        user = C.WinDLL("user32", use_last_error=True, winmode=0x800)
        self.station = _bind(user, "GetProcessWindowStation", PTR)
        self.desktop = _bind(user, "GetThreadDesktop", PTR, DWORD)
        self.info = _bind(user, "GetUserObjectInformationW", BOOL, PTR, C.c_int32, PTR, DWORD, C.POINTER(DWORD))
        self.thread = _bind(api.kernel, "GetCurrentThreadId", DWORD)
        self.get = _bind(api.security, "GetSecurityInfo", DWORD,
                         PTR, C.c_int32, DWORD, PTR, PTR, PTR, PTR, C.POINTER(PTR))
        self.set = _bind(api.security, "SetSecurityInfo", DWORD, PTR, C.c_int32, DWORD, PTR, PTR, PTR, PTR)
        self.dacl = _bind(api.security, "GetSecurityDescriptorDacl", BOOL,
                          PTR, C.POINTER(BOOL), C.POINTER(PTR), C.POINTER(BOOL))

    def targets(self):
        station = self.station()
        self.api.check(station, "GetProcessWindowStation")
        name = C.create_unicode_buffer(256)
        self.api.check(self.info(station, 2, name, C.sizeof(name), None), "GetUserObjectInformationW")
        if name.value.casefold() == "winsta0":
            return []
        desktop = self.desktop(self.thread())
        self.api.check(desktop, "GetThreadDesktop")
        return [(station, self.STATION), (desktop, self.DESKTOP)]

    def read(self, handle):
        descriptor = PTR()
        # SE_WINDOW_OBJECT=7.
        code = self.get(handle, 7, 4, None, None, None, None, C.byref(descriptor))
        if code:
            raise OSError(f"GetSecurityInfo(window object): {C.WinError(code)}")
        try:
            return self.text(descriptor)
        finally:
            self.api.local_free(descriptor)

    def write(self, handle, sddl):
        descriptor, present, dacl, defaulted = self.descriptor(sddl), BOOL(), PTR(), BOOL()
        try:
            self.api.check(self.dacl(descriptor, C.byref(present), C.byref(dacl), C.byref(defaulted)),
                           "GetSecurityDescriptorDacl")
            code = self.set(handle, 7, 4, None, None, dacl, None)
            if code:
                raise OSError(f"SetSecurityInfo(window object): {C.WinError(code)}")
        finally:
            self.api.local_free(descriptor)


class _Files(_Dacl):
    """One file or folder's DACL. SetFileSecurityW changes only the named object,
    unlike icacls, which re-propagates inherited entries through the whole subtree."""
    ATTRIBUTES = 0x100080  # FILE_READ_ATTRIBUTES | SYNCHRONIZE
    VOLUME = 0x100081  # ... | FILE_LIST_DIRECTORY: top-level names only, nothing below

    def __init__(self, api):
        super().__init__(api)
        self.get = _bind(api.security, "GetFileSecurityW", BOOL, WSTR, DWORD, PTR, DWORD, C.POINTER(DWORD))
        self.set = _bind(api.security, "SetFileSecurityW", BOOL, WSTR, DWORD, PTR)

    def read(self, path):
        size = DWORD()
        self.get(str(path), 4, None, 0, C.byref(size))
        if not size.value:
            self.api.check(False, f"GetFileSecurityW({path})")
        buffer = C.create_string_buffer(size.value)
        self.api.check(self.get(str(path), 4, buffer, size, C.byref(size)), f"GetFileSecurityW({path})")
        return self.text(buffer)

    def write(self, path, sddl, information=4):
        """DACL_SECURITY_INFORMATION by default; LABEL_SECURITY_INFORMATION is 0x10."""
        descriptor = self.descriptor(sddl)
        try:
            self.api.check(self.set(str(path), information, descriptor), f"SetFileSecurityW({path})")
        finally:
            self.api.local_free(descriptor)


# CPython 3.12.4+ gives os.mkdir(path, 0o700) a protected DACL for SYSTEM, Administrators
# and the owner only (CVE-2024-4030). An AppContainer cannot open such a folder, which
# breaks tempfile.mkdtemp, venv, pip and pytest. Sandboxed Python loads this through
# PYTHONPATH and adds only this sandbox's SID to that DACL, then any project shim.
_PYTHON_SHIM = r'''"""Eirene Windows sandbox: private CPython folders must admit this AppContainer."""
import os
import sys


def _patch_private_mkdir():
    sid = os.environ.get("EIRENE_SANDBOX_SID")
    if os.name != "nt" or not sid:
        return
    import ctypes
    from ctypes import wintypes

    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]

    convert = ctypes.WinDLL("advapi32", use_last_error=True).ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create, free = kernel.CreateDirectoryW, kernel.LocalFree
    create.argtypes, create.restype = [wintypes.LPCWSTR, ctypes.c_void_p], wintypes.BOOL
    free.argtypes, free.restype = [ctypes.c_void_p], ctypes.c_void_p
    sddl = f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)(A;OICI;FA;;;{sid})"
    original = os.mkdir

    def mkdir(path, mode=0o777, *, dir_fd=None):
        if mode != 0o700 or dir_fd is not None:
            return original(path, mode, dir_fd=dir_fd)
        name = os.fsdecode(os.fspath(path))
        descriptor = ctypes.c_void_p()
        if not convert(sddl, 1, ctypes.byref(descriptor), None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not create(name, ctypes.byref(Attributes(ctypes.sizeof(Attributes), descriptor, False))):
                error = ctypes.get_last_error()
                raise OSError(None, ctypes.FormatError(error), name, error)
        finally:
            free(descriptor)

    os.mkdir = mkdir


def _keep_shim_in_venv():
    """venv drops PYTHONPATH before bootstrapping pip; give its children this folder back."""
    if not os.environ.get("EIRENE_SANDBOX_SID"):
        return
    import importlib.machinery
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))

    class Subprocess:
        def __getattr__(self, name):
            return getattr(subprocess, name)

        def check_output(self, args, **kwargs):
            env = kwargs.get("env")
            if env is not None and not env.get("PYTHONPATH"):
                env["PYTHONPATH"] = here
            return subprocess.check_output(args, **kwargs)

    class Finder:
        def find_spec(self, name, path=None, target=None):
            if name != "venv":
                return None
            # runpy looks venv up before importing it; stay until the import itself.
            spec = importlib.machinery.PathFinder.find_spec(name, path)
            if spec and spec.loader:
                load = spec.loader.exec_module

                def exec_module(module):
                    load(module)
                    module.subprocess = Subprocess()
                    if self in sys.meta_path:
                        sys.meta_path.remove(self)
                spec.loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, Finder())


def _chain():
    """Run a sitecustomize further down sys.path, which this file would otherwise hide."""
    import importlib.machinery
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    rest = [entry for entry in sys.path if os.path.abspath(entry or ".") != here]
    spec = importlib.machinery.PathFinder.find_spec("sitecustomize", rest)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)


_patch_private_mkdir()
_keep_shim_in_venv()
_chain()
'''

TOOLCHAINS = "Eirene.Sandbox.Toolchains"
# internetClient, internetClientServer, privateNetworkClientServer.
NETWORK = ("S-1-15-3-1", "S-1-15-3-2", "S-1-15-3-3")
_setup = threading.Lock()
_ready = set()


def _icacls(path, *arguments):
    executable = str(Path(os.environ["SystemRoot"]) / "System32" / "icacls.exe")
    try:
        result = subprocess.run([executable, str(path), *arguments, "/L", "/Q"],
                                capture_output=True, timeout=600, creationflags=0x08000000)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"Windows sandbox ACL operation timed out: {path}") from exc
    if result.returncode:
        raise ToolError(f"Windows sandbox cannot update ACL for {path}: "
                        + result.stderr.decode(errors="replace")[:1000])


def _specific(path):
    path = Path(path).resolve(strict=True)
    if path == Path(path.anchor) or str(path).startswith("\\\\"):
        raise ToolError("Windows sandbox grants require a specific local path, not a volume root or network share")
    return path


def _profile_name(root, read_only, network):
    """Read-only and network-approved commands get their own workspace profiles, so a
    loopback exemption for approved networking never reaches ordinary commands."""
    digest = hashlib.sha256(str(root).casefold().encode()).hexdigest()[:32]
    return "Eirene.Workspace." + ("RO." if read_only else "") + ("Net." if network else "") + digest


def _toolchains(executable):
    """User-installed runtimes on PATH, which the AppContainer could not otherwise load.

    Windows and Program Files already admit AppContainers. Broad profile folders and
    anything holding Eirene's own data are never granted; launcher folders such as
    Scripts or cmd bring their install root, and a few launchers their real store.
    """
    home = Path.home().resolve()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local").resolve()
    roaming = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming").resolve()
    broad = {home, home / "AppData", local, roaming, local / "Programs", local / "Temp",
             local / "Microsoft", local / "Microsoft" / "WindowsApps", home / ".local"}
    system = [Path(os.environ[key]).resolve() for key in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)")
              if os.environ.get(key)]
    companions = {home / ".cargo": [home / ".rustup"], home / ".local" / "bin": [roaming / "uv" / "python"]}
    private = paths.home().resolve()
    found = []
    for entry in [Path(executable).parent, *(Path(p) for p in os.environ.get("PATH", "").split(os.pathsep) if p)]:
        try:
            entry = entry.resolve(strict=True)
        except OSError:
            continue
        candidates = [entry, *companions.get(entry, [])]
        if entry.name.casefold() in {"bin", "cmd", "scripts", "shims"} and entry.parent not in broad:
            candidates = [entry.parent, *companions.get(entry.parent, [])]
        for candidate in candidates:
            if (candidate.is_dir() and candidate not in broad and candidate != Path(candidate.anchor)
                    and not str(candidate).startswith("\\\\")
                    and not any(candidate in folder.parents for folder in broad)
                    and not any(candidate == folder or folder in candidate.parents for folder in system)
                    and not (candidate == private or candidate in private.parents)):
                found.append(candidate)
    return list(dict.fromkeys(found))


class _Executables:
    """Gives programs a command creates the normal Medium integrity label afterwards.

    Everything an AppContainer creates is labelled Low, and Windows starts a program
    whose file is labelled Low at Low integrity even from the user's own shell: a venv
    built in the sandbox could not then read its own pyvenv.cfg. Data files are not
    affected, as a Low label only limits writes by lower-integrity processes.
    """
    SUFFIXES = (".exe", ".com")
    MEDIUM = "S:(ML;;NW;;;ME)"

    def __init__(self, api, roots):
        self.api = api
        self.started = time.time()
        self.found, self.overflowed = set(), set()
        kernel = api.kernel
        self.open = _bind(kernel, "CreateFileW", PTR, WSTR, DWORD, DWORD, PTR, DWORD, DWORD, PTR)
        self.read = _bind(kernel, "ReadDirectoryChangesW", BOOL,
                          PTR, PTR, DWORD, BOOL, DWORD, C.POINTER(DWORD), PTR, PTR)
        self.open_thread = _bind(kernel, "OpenThread", PTR, DWORD, BOOL, DWORD)
        self.cancel = _bind(kernel, "CancelSynchronousIo", BOOL, PTR)
        self.watchers = []
        for root in roots:
            # FILE_LIST_DIRECTORY; share everything; OPEN_EXISTING; FILE_FLAG_BACKUP_SEMANTICS.
            handle = self.open(str(root), 0x1, 0x7, None, 3, 0x02000000, None)
            if handle in (None, C.c_void_p(-1).value):
                self.overflowed.add(root)  # Cannot watch: scan afterwards instead.
                continue
            watcher = threading.Thread(target=self._watch, args=(root, handle), daemon=True)
            self.watchers.append((watcher, handle))
            watcher.start()

    def _watch(self, root, handle):
        buffer, returned = C.create_string_buffer(65536), DWORD()
        while self.read(handle, buffer, len(buffer), True, 0x1, C.byref(returned), None, None):  # FILE_NAME
            if not returned.value:
                self.overflowed.add(root)
                continue
            offset = 0
            while True:
                following, action, length = struct.unpack_from("<III", buffer, offset)
                name = buffer.raw[offset + 12:offset + 12 + length].decode("utf-16-le")
                if action in (1, 5) and name.casefold().endswith(self.SUFFIXES):  # added, renamed to
                    self.found.add(root / name)
                if not following:
                    break
                offset += following

    def finish(self):
        for watcher, handle in self.watchers:
            while watcher.is_alive():
                thread = self.open_thread(0x1, False, watcher.native_id or 0)  # THREAD_TERMINATE
                if thread:
                    self.cancel(thread)
                    self.api.close_handle(thread)
                watcher.join(0.05)
            self.api.close_handle(handle)
        self.watchers = []
        for root in self.overflowed:
            self.found.update(self._scan(root))
        files = _Files(self.api)
        for path in self.found:
            try:
                if path.is_file() and not path.is_symlink():
                    files.write(path, self.MEDIUM, 0x10)
            except OSError:
                pass  # Removed meanwhile, or not ours to relabel.

    def _scan(self, root):
        """Executables changed during the command; never descends through reparse points."""
        pending = [root]
        while pending:
            try:
                entries = list(os.scandir(pending.pop()))
            except OSError:
                continue
            for entry in entries:
                attributes = entry.stat(follow_symlinks=False)
                if getattr(attributes, "st_file_attributes", 0) & 0x400:
                    continue
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.name.casefold().endswith(self.SUFFIXES) and attributes.st_mtime >= self.started - 2:
                    yield Path(entry.path)


class Owner:
    def __init__(self, name, capabilities):
        self.box = AppContainer(name, capabilities)
        self.api = self.box._api
        self.grants = []
        self.files = []
        self.native = None
        self.executables = None

    def persist(self, path, sid, permissions):
        """Grant once per workspace; only the first grant propagates through the tree."""
        key = (sid, str(path).casefold(), permissions)
        if key in _ready:
            return
        if not _Files(self.api).has(path, sid):
            _icacls(path, "/grant", f"*{sid}:{permissions}")
        _ready.add(key)

    def persist_window_objects(self, sid):
        windows = _WindowObjects(self.api)
        for handle, rights in windows.targets():
            if not windows.has(handle, sid):
                windows.grant(handle, sid, rights)

    def persist_ancestors(self, root, sid):
        """Read-attributes on the folders above the workspace, so tools can stat their way down.

        Git's repository discovery and leading-directory creation stat every path
        component; without this an AppContainer fails at the first parent. Nothing
        is listed, read or inherited. Folders the user cannot re-ACL are skipped.
        """
        files = _Files(self.api)
        for path in root.parents:
            key = (sid, str(path).casefold(), "ancestor")
            if path == Path(path.anchor) or key in _ready:
                continue
            try:
                if not files.has(path, sid):
                    files.grant(path, sid, files.ATTRIBUTES)
            except OSError:
                pass  # Not ours to re-ACL, such as C:\Users.
            _ready.add(key)

    def persist_volume_root(self, root, sid):
        """Lets dir, vol and PowerShell open the drive root; needs an elevated Eirene once."""
        volume = Path(root.anchor)
        key = (sid, str(volume).casefold(), "volume")
        if key in _ready:
            return
        files = _Files(self.api)
        try:
            if not files.has(volume, sid):
                files.grant(volume, sid, files.VOLUME)
        except OSError:
            pass  # Unelevated; PowerShell falls back to its Workspace:\ drive.
        _ready.add(key)

    def persist_loopback(self, sid):
        """Approved networking reaches host services on localhost, as on Linux; needs an elevated Eirene."""
        key = (sid, "loopback")
        if key in _ready:
            return
        _ready.add(key)
        shell32 = C.WinDLL("shell32", use_last_error=True, winmode=0x800)
        if not shell32.IsUserAnAdmin():
            return
        executable = str(Path(os.environ["SystemRoot"]) / "System32" / "CheckNetIsolation.exe")
        subprocess.run([executable, "LoopbackExempt", "-a", f"-p={sid}"],
                       capture_output=True, timeout=30, creationflags=0x08000000)

    def grant(self, path, sid, writable):
        path = _specific(path)
        permissions = ("(OI)(CI)" if path.is_dir() else "") + ("M" if writable else "RX")
        # Record before mutation: a failed icacls operation may be partial.
        self.grants.append((path, sid))
        _icacls(path, "/grant", f"*{sid}:{permissions}")

    def close(self):
        if self.native:
            self.native.close()
        for file in self.files:
            file.close()
        for file in self.files:
            Path(file.name).unlink(missing_ok=True)
        self.files = []
        if self.executables:
            self.executables.finish()
            self.executables = None
        while self.grants:
            path, sid = self.grants[-1]
            if path.exists():
                _icacls(path, "/remove:g", f"*{sid}")
            self.grants.pop()
        self.box.close()


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


class _PipeWriter:
    """asyncio StreamWriter subset over a blocking pipe; writes leave the event loop."""
    def __init__(self, fd):
        self.fd = fd
        self.buffer = bytearray()
        self.lock = asyncio.Lock()

    def write(self, data):
        self.buffer += data

    async def drain(self):
        async with self.lock:
            data, self.buffer = bytes(self.buffer), bytearray()
            await asyncio.to_thread(self._write_all, data)

    def _write_all(self, data):
        view = memoryview(data)
        while view:
            view = view[os.write(self.fd, view):]

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def _feed(loop, fd, reader):
    def deliver(method, *args):
        try:
            loop.call_soon_threadsafe(method, *args)
        except RuntimeError:
            pass  # The loop closed first; nobody is reading.
    try:
        while chunk := os.read(fd, 65536):
            deliver(reader.feed_data, chunk)
    except OSError:
        pass
    finally:
        os.close(fd)
        deliver(reader.feed_eof)


class StreamProcess:
    """Pipe-backed asyncio subprocess interface for long-lived servers such as MCP.

    The sandbox is released once the command exits; killing it ends the whole Job.
    """
    def __init__(self, owner, stdin, stdout, stderr, *, limit):
        loop = asyncio.get_running_loop()
        self.owner = owner
        self.native = owner.native
        self.pid = self.native.pid
        self.returncode = None
        self._eirene_job = self.native._job
        self.stdin = _PipeWriter(stdin)
        self.stdout = asyncio.StreamReader(limit=limit)
        self.stderr = asyncio.StreamReader(limit=limit)
        for fd, reader in ((stdout, self.stdout), (stderr, self.stderr)):
            threading.Thread(target=_feed, args=(loop, fd, reader), daemon=True).start()
        self._task = asyncio.create_task(self._wait())

    async def _wait(self):
        while True:
            try:
                self.returncode = self.native.wait(0)
                break
            except TimeoutError:
                await asyncio.sleep(0.05)
        self.stdin.close()
        self.owner.close()
        return self.returncode

    async def wait(self):
        return await asyncio.shield(self._task)

    def kill(self):
        self._eirene_job.terminate()


def _spawn(owner, argv, cwd, env, temp, handles):
    """Children inherit exactly these handles; they are inheritable only during creation."""
    try:
        for handle in set(handles):
            os.set_handle_inheritable(handle, True)
        owner.native = owner.box.spawn(argv, cwd=cwd, env=env, std_handles=handles, temp=temp)
    finally:
        for handle in set(handles):
            os.set_handle_inheritable(handle, False)


def _streaming(owner, argv, cwd, env, temp, limit):
    import msvcrt
    pipes = [os.pipe() for _ in range(3)]
    child = (pipes[0][0], pipes[1][1], pipes[2][1])
    parent = (pipes[0][1], pipes[1][0], pipes[2][0])
    try:
        _spawn(owner, argv, cwd, env, temp, tuple(msvcrt.get_osfhandle(fd) for fd in child))
    except BaseException:
        for fd in (*child, *parent):
            os.close(fd)
        raise
    for fd in child:
        os.close(fd)
    return StreamProcess(owner, *parent, limit=limit)


async def start(argv, root, cwd, *, network=False, read_paths=(), write_paths=(),
                read_only=False, env=None, input_text=None, streams=False, limit=2 ** 16):
    """Start a sandboxed command. Bounded input and file-backed output by default;
    streams=True gives live stdin/stdout/stderr pipes for protocol servers such as MCP."""
    if os.name != "nt":
        raise ToolError("Windows AppContainer runtime requires Windows")
    if read_only and write_paths:
        raise ToolError("read-only execution cannot grant writable paths")
    root = _specific(root)
    cwd = Path(cwd).resolve(strict=True)
    reads = [(root / Path(p).expanduser()).resolve(strict=True) for p in read_paths]
    writes = [(root / Path(p).expanduser()).resolve(strict=True) for p in write_paths]
    if not any(cwd == path or path in cwd.parents for path in [root, *reads, *writes]):
        raise ToolError("Windows command working directory leaves its grants")
    executable = shutil.which(argv[0])
    if not executable:
        raise ToolError(f"Windows command executable is unavailable: {argv[0]}")
    argv = [executable, *argv[1:]]
    api = _Win32()
    toolchains = api.capability(TOOLCHAINS)
    # Approved extra paths belong to this command only, through a capability no other token has.
    extra = api.capability("Eirene.Grant." + uuid.uuid4().hex) if reads or writes else None
    capabilities = [toolchains, *([extra] if extra else []), *(NETWORK if network else ())]
    owner = Owner(_profile_name(root, read_only, network), capabilities)
    try:
        sid = owner.box.sid
        temp = None if read_only else paths.temp_dir()
        with _setup:
            owner.persist(root, sid, "(OI)(CI)" + ("RX" if read_only else "M"))
            if temp:
                owner.persist(temp, sid, "(OI)(CI)M")
            owner.persist_ancestors(root, sid)
            owner.persist_window_objects(sid)
            owner.persist_volume_root(root, toolchains)
            if network:
                owner.persist_loopback(sid)
            for folder in _toolchains(executable):
                owner.persist(folder, toolchains, "(OI)(CI)RX")
        for path, writable in [*((p, False) for p in reads), *((p, True) for p in writes)]:
            owner.grant(path, extra, writable)
        if not read_only:
            owner.executables = _Executables(owner.api, [root, *writes])
        shim = owner.box.home / "python" / "sitecustomize.py"
        if not shim.is_file() or shim.read_text(encoding="utf-8") != _PYTHON_SHIM:
            shim.parent.mkdir(exist_ok=True)
            shim.write_text(_PYTHON_SHIM, encoding="utf-8")
        # PowerShell resolves bare names such as git or whoami through PATHEXT.
        # The package token hides Administrators ownership of the workspace, so
        # git's ownership check would reject it; trust only the workspace.
        env = {"PATH": os.environ.get("PATH", ""),
               "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
               "GIT_CONFIG_COUNT": "2",
               "GIT_CONFIG_KEY_0": "safe.directory", "GIT_CONFIG_VALUE_0": root.as_posix(),
               "GIT_CONFIG_KEY_1": "safe.directory", "GIT_CONFIG_VALUE_1": root.as_posix() + "/*",
               "PYTHONPATH": str(shim.parent), "EIRENE_SANDBOX_SID": sid,
               **(env or {})}
        if streams:
            return _streaming(owner, argv, cwd, env, temp, limit)
        # Unique names: commands of one workspace share the profile's private storage.
        name = uuid.uuid4().hex
        stdin = (owner.box.home / f"{name}.in").open("w+b")
        owner.files.append(stdin)
        stdin.write((input_text or "").encode("utf-8"))
        stdin.seek(0)
        stdout = (owner.box.home / f"{name}.out").open("w+b")
        owner.files.append(stdout)
        output = (owner.box.home / f"{name}.out").open("rb")
        owner.files.append(output)
        import msvcrt
        handles = (msvcrt.get_osfhandle(stdin.fileno()), msvcrt.get_osfhandle(stdout.fileno()))
        _spawn(owner, argv, cwd, env, temp, (handles[0], handles[1], handles[1]))
        return AsyncProcess(owner, output)
    except BaseException:
        owner.close()
        raise
