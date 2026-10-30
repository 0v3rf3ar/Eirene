"""Windows AppContainer process creation with verified kernel tokens.

No command reaches ResumeThread until its kernel token has been checked and it
belongs to a kill-on-close Job. No credentials or handles are inherited except
explicitly supplied standard handles, and the token carries exactly the
capabilities the runtime requested. Workspace grants are
managed by windows_runtime. See docs/windows-sandbox.md for the boundary.
"""

from __future__ import annotations

import ctypes as C
import math
import os
import subprocess
import uuid
from pathlib import Path, PureWindowsPath

from ..core.errors import ToolError

# Fixed-width Win32 types also make structure layout checks meaningful on Linux.
DWORD = C.c_uint32
BOOL = C.c_int32
PTR = C.c_void_p
WSTR = C.c_wchar_p
SIZE = C.c_size_t


class SecurityCapabilities(C.Structure):
    _fields_ = [("sid", PTR), ("capabilities", PTR),
                ("count", DWORD), ("reserved", DWORD)]


class SidAndAttributes(C.Structure):
    _fields_ = [("sid", PTR), ("attributes", DWORD)]


class StartupInfo(C.Structure):
    _fields_ = [("cb", DWORD), ("reserved", WSTR), ("desktop", WSTR),
                ("title", WSTR), ("x", DWORD), ("y", DWORD),
                ("x_size", DWORD), ("y_size", DWORD), ("x_chars", DWORD),
                ("y_chars", DWORD), ("fill", DWORD), ("flags", DWORD),
                ("show", C.c_uint16), ("reserved_size", C.c_uint16),
                ("reserved_ptr", PTR), ("stdin", PTR), ("stdout", PTR),
                ("stderr", PTR)]


class StartupInfoEx(C.Structure):
    _fields_ = [("startup", StartupInfo), ("attributes", PTR)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", PTR), ("thread", PTR),
                ("pid", DWORD), ("tid", DWORD)]


def _command_line(argv) -> str:
    if (not isinstance(argv, (list, tuple)) or not argv
            or not all(isinstance(arg, str) and "\0" not in arg for arg in argv)
            or not argv[0] or not Path(argv[0]).is_absolute()):
        raise ToolError("AppContainer requires an absolute executable and NUL-free string arguments")
    command = subprocess.list2cmdline(argv)
    if PureWindowsPath(argv[0]).name.casefold() == "cmd.exe" and tuple(argv[1:4]) == ("/d", "/s", "/c") and len(argv) == 5:
        # cmd parses its own command line: /s /c removes the outer quotes and runs the
        # rest verbatim, so exec-style escaping (\") would corrupt quoted paths.
        command = subprocess.list2cmdline(argv[:4]) + ' "' + argv[4] + '"'
    # CreateProcessW's limit includes the terminator and counts UTF-16 units.
    if len(command.encode("utf-16-le")) // 2 >= 32767:
        raise ToolError("AppContainer command exceeds the Windows command-line limit")
    return command


def _environment(system_root: str, home: Path, local_appdata: str, extra=None, temp=None) -> str:
    """An explicit, minimal Unicode environment; never inherit the host's secrets."""
    # CreateProcessW needs the host profile location to resolve AppContainer
    # storage. Omitting LOCALAPPDATA produces ERROR_ENVVAR_NOT_FOUND (203).
    # Windows redirects LOCALAPPDATA for the AppContainer child itself.
    if not local_appdata or "\0" in local_appdata or not Path(local_appdata).is_absolute():
        raise ToolError("AppContainer requires an absolute LOCALAPPDATA to resolve its profile")
    values = {
        "SystemRoot": system_root, "WINDIR": system_root,
        "LOCALAPPDATA": local_appdata,
        "PATH": str(Path(system_root) / "System32"),
        "COMSPEC": str(Path(system_root) / "System32" / "cmd.exe"),
        "HOME": str(home), "USERPROFILE": str(home),
        "TEMP": str(temp or home), "TMP": str(temp or home),
    }
    protected = {key.upper() for key in values if key != "PATH"}
    for key, value in (extra or {}).items():
        if not isinstance(key, str) or not key or "=" in key or "\0" in key or not isinstance(value, str):
            raise ToolError("invalid AppContainer environment entry")
        if key.upper() not in protected:
            # Windows environment keys are case insensitive.
            values = {k: v for k, v in values.items() if k.upper() != key.upper()}
            values[key] = value
    if any("\0" in value for value in values.values()):
        raise ToolError("AppContainer environment contains NUL")
    return "\0".join(f"{key}={values[key]}" for key in sorted(values, key=str.upper)) + "\0\0"


class _Win32:
    """Bindings are lazy: importing Eirene on other platforms stays safe."""

    def __init__(self):
        if os.name != "nt":
            raise ToolError("AppContainer process creation requires Windows")
        # Resolve OS libraries only in System32, never in an untrusted workspace.
        self.kernel = C.WinDLL("kernel32", use_last_error=True, winmode=0x800)
        self.security = C.WinDLL("advapi32", use_last_error=True, winmode=0x800)
        self.userenv = C.WinDLL("userenv", use_last_error=True, winmode=0x800)
        self.ole = C.WinDLL("ole32", use_last_error=True, winmode=0x800)

        def bind(dll, name, result, *args):
            function = getattr(dll, name)
            function.restype = result
            function.argtypes = list(args)
            return function

        self.create_profile = bind(self.userenv, "CreateAppContainerProfile", C.c_int32,
                                   WSTR, WSTR, WSTR, PTR, DWORD, C.POINTER(PTR))
        self.derive_profile = bind(self.userenv, "DeriveAppContainerSidFromAppContainerName", C.c_int32,
                                   WSTR, C.POINTER(PTR))
        self.kernelbase = C.WinDLL("kernelbase", use_last_error=True, winmode=0x800)
        self.derive_capability = bind(self.kernelbase, "DeriveCapabilitySidsFromName", BOOL, WSTR,
                                      C.POINTER(C.POINTER(PTR)), C.POINTER(DWORD),
                                      C.POINTER(C.POINTER(PTR)), C.POINTER(DWORD))
        self.string_sid = bind(self.security, "ConvertStringSidToSidW", BOOL, WSTR, C.POINTER(PTR))
        self.delete_profile = bind(self.userenv, "DeleteAppContainerProfile", C.c_int32, WSTR)
        self.get_folder = bind(self.userenv, "GetAppContainerFolderPath", C.c_int32,
                               WSTR, C.POINTER(PTR))
        self.free_sid = bind(self.security, "FreeSid", PTR, PTR)
        self.sid_text = bind(self.security, "ConvertSidToStringSidW", BOOL, PTR, C.POINTER(PTR))
        self.local_free = bind(self.kernel, "LocalFree", PTR, PTR)
        self.task_free = bind(self.ole, "CoTaskMemFree", None, PTR)
        self.init_attributes = bind(self.kernel, "InitializeProcThreadAttributeList", BOOL,
                                    PTR, DWORD, DWORD, C.POINTER(SIZE))
        self.update_attribute = bind(self.kernel, "UpdateProcThreadAttribute", BOOL,
                                     PTR, DWORD, SIZE, PTR, SIZE, PTR, PTR)
        self.delete_attributes = bind(self.kernel, "DeleteProcThreadAttributeList", None, PTR)
        self.create_process = bind(self.kernel, "CreateProcessW", BOOL,
                                   WSTR, WSTR, PTR, PTR, BOOL, DWORD, PTR, WSTR,
                                   C.POINTER(StartupInfoEx), C.POINTER(ProcessInfo))
        self.open_token = bind(self.security, "OpenProcessToken", BOOL, PTR, DWORD, C.POINTER(PTR))
        self.token_info = bind(self.security, "GetTokenInformation", BOOL,
                               PTR, C.c_int32, PTR, DWORD, C.POINTER(DWORD))
        self.equal_sid = bind(self.security, "EqualSid", BOOL, PTR, PTR)
        self._close_handle = bind(self.kernel, "CloseHandle", BOOL, PTR)
        self.terminate_process = bind(self.kernel, "TerminateProcess", BOOL, PTR, DWORD)
        self.wait_object = bind(self.kernel, "WaitForSingleObject", DWORD, PTR, DWORD)
        self.exit_code = bind(self.kernel, "GetExitCodeProcess", BOOL, PTR, C.POINTER(DWORD))
        self.resume_thread = bind(self.kernel, "ResumeThread", DWORD, PTR)

    @staticmethod
    def check(ok, operation):
        if not ok:
            raise OSError(f"{operation}: {C.WinError(C.get_last_error())}")

    @staticmethod
    def hresult(code, operation):
        if code < 0:
            raise OSError(f"{operation}: HRESULT 0x{code & 0xffffffff:08x}")

    def profile(self, name):
        sid = PTR()
        code = self.create_profile(name, name, "Eirene command sandbox", None, 0, C.byref(sid))
        if code & 0xffffffff == 0x800700B7:  # ERROR_ALREADY_EXISTS: a persistent workspace profile.
            code = self.derive_profile(name, C.byref(sid))
        self.hresult(code, "CreateAppContainerProfile")
        return sid

    def sid_string(self, sid):
        text = PTR()
        self.check(self.sid_text(sid, C.byref(text)), "ConvertSidToStringSidW")
        try:
            return C.wstring_at(text)
        finally:
            self.local_free(text)

    def capability(self, name):
        """The SID Windows derives for a named custom capability."""
        groups, group_count, sids, sid_count = C.POINTER(PTR)(), DWORD(), C.POINTER(PTR)(), DWORD()
        self.check(self.derive_capability(name, C.byref(groups), C.byref(group_count),
                                          C.byref(sids), C.byref(sid_count)), "DeriveCapabilitySidsFromName")
        try:
            if sid_count.value != 1:
                raise ToolError(f"unexpected capability SIDs for {name}")
            return self.sid_string(sids[0])
        finally:
            for array, count in ((groups, group_count.value), (sids, sid_count.value)):
                for index in range(count):
                    self.local_free(array[index])
                self.local_free(C.cast(array, PTR))

    def capability_sids(self, texts):
        values = []
        try:
            for text in texts:
                sid = PTR()
                self.check(self.string_sid(text, C.byref(sid)), f"ConvertStringSidToSidW({text})")
                values.append(sid)
        except BaseException:
            self.free_capabilities(values)
            raise
        return values

    def free_capabilities(self, values):
        for sid in values:
            self.local_free(sid)

    def folder(self, sid):
        text = PTR()
        folder = PTR()
        try:
            self.check(self.sid_text(sid, C.byref(text)), "ConvertSidToStringSidW")
            self.hresult(self.get_folder(C.wstring_at(text), C.byref(folder)),
                         "GetAppContainerFolderPath")
            return Path(C.wstring_at(folder))
        finally:
            if folder:
                self.task_free(folder)
            if text:
                self.local_free(text)

    def suspended(self, argv, cwd, environment, sid, *, std_handles=None, capabilities=()):
        size = SIZE()
        count = 2 if std_handles else 1
        self.init_attributes(None, count, 0, C.byref(size))
        if not size.value:
            self.check(False, "InitializeProcThreadAttributeList(size)")
        attributes = C.create_string_buffer(size.value)
        self.check(self.init_attributes(attributes, count, 0, C.byref(size)),
                   "InitializeProcThreadAttributeList")
        try:
            # Only the capabilities the runtime asked for: no network unless approved.
            granted = (SidAndAttributes * len(capabilities))(
                *(SidAndAttributes(value, 0x4) for value in capabilities)) if capabilities else None  # SE_GROUP_ENABLED
            security = SecurityCapabilities(sid, C.cast(granted, PTR) if granted else None, len(capabilities), 0)
            self.check(self.update_attribute(attributes, 0, 0x00020009,
                                             C.byref(security), C.sizeof(security), None, None),
                       "UpdateProcThreadAttribute(SECURITY_CAPABILITIES)")
            startup = StartupInfoEx()
            startup.startup.cb = C.sizeof(startup)
            startup.attributes = C.cast(attributes, PTR)
            if std_handles:
                handles = (PTR * len(set(std_handles)))(*dict.fromkeys(std_handles))
                self.check(self.update_attribute(attributes, 0, 0x00020002,
                                                 handles, C.sizeof(handles), None, None),
                           "UpdateProcThreadAttribute(HANDLE_LIST)")
                startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
                startup.startup.stdin, startup.startup.stdout, startup.startup.stderr = std_handles
            info = ProcessInfo()
            command = C.create_unicode_buffer(_command_line(argv))
            env = C.create_unicode_buffer(environment)
            # Suspended + Unicode environment + extended startup + no console.
            flags = 0x00000004 | 0x00000400 | 0x00080000 | 0x08000000
            self.check(self.create_process(argv[0], command, None, None, bool(std_handles),
                                            flags, env, str(cwd), C.byref(startup), C.byref(info)),
                       "CreateProcessW(AppContainer)")
            return info
        finally:
            self.delete_attributes(attributes)

    def _token_value(self, token, kind):
        size = DWORD()
        self.token_info(token, kind, None, 0, C.byref(size))
        if not size.value:
            self.check(False, "GetTokenInformation(size)")
        buffer = C.create_string_buffer(size.value)
        self.check(self.token_info(token, kind, buffer, size, C.byref(size)), "GetTokenInformation")
        return buffer

    def verify(self, process, sid, capabilities=()):
        expected = list(capabilities)
        token = PTR()
        self.check(self.open_token(process, 0x0008, C.byref(token)), "OpenProcessToken")
        try:
            # TOKEN_INFORMATION_CLASS: IsAppContainer=29, Capabilities=30, SID=31.
            is_container = self._token_value(token, 29)
            actual_sid = self._token_value(token, 31)
            capabilities = self._token_value(token, 30)
            count = DWORD.from_buffer(capabilities).value
            if (DWORD.from_buffer(is_container).value != 1
                    or not self.equal_sid(PTR.from_buffer(actual_sid), sid)
                    or count != len(expected)):
                raise ToolError("AppContainer token verification failed; command was not resumed")
            # TOKEN_GROUPS: a DWORD count, then pointer-aligned SID_AND_ATTRIBUTES entries.
            offset = C.sizeof(PTR)
            actual = (SidAndAttributes * count).from_buffer(capabilities, offset) if count else []
            if not all(any(self.equal_sid(entry.sid, value) for entry in actual) for value in expected):
                raise ToolError("AppContainer token verification failed; command was not resumed")
        finally:
            self.close_handle(token)

    def attach(self, pid):
        from .windows_jobs import own
        return own(pid, resume=False)

    def resume(self, thread):
        if self.resume_thread(thread) != 1:
            raise ToolError("AppContainer thread did not have the expected suspension count")

    def wait(self, process, timeout):
        if not math.isfinite(timeout) or timeout < 0 or timeout * 1000 >= 0xffffffff:
            raise ValueError("timeout must be finite and fit a Windows wait")
        status = self.wait_object(process, math.ceil(timeout * 1000))
        if status == 258:  # WAIT_TIMEOUT
            raise TimeoutError("AppContainer process is still running")
        self.check(status == 0, "WaitForSingleObject")
        code = DWORD()
        self.check(self.exit_code(process, C.byref(code)), "GetExitCodeProcess")
        return code.value

    def abort(self, process):
        # A failure here must prevent profile deletion while a child may survive.
        if self.wait_object(process, 0) != 0:
            if not self.terminate_process(process, 1):
                # Job assignment failure can already have killed the process.
                self.check(self.wait_object(process, 0) == 0, "TerminateProcess")
        self.wait(process, 5)

    def close_handle(self, handle):
        self.check(self._close_handle(handle), "CloseHandle")

    def remove_profile(self, name, sid):
        self.hresult(self.delete_profile(name), "DeleteAppContainerProfile")
        self.free_sid(sid)


class Process:
    """Synchronous native process owner; the async supervisor is a later step."""

    def __init__(self, api, info, job=None):
        self._api, self._info, self._job = api, info, job
        self.pid = info.pid
        self.returncode = None
        self.closed = False

    def wait(self, timeout=30):
        if self.closed:
            if self.returncode is None:
                raise ToolError("AppContainer process is closed")
            return self.returncode
        self.returncode = self._api.wait(self._info.process, timeout)
        return self.returncode

    def close(self):
        if not self.closed:
            if self._job is not None:
                self._job.terminate()
            else:
                self._api.abort(self._info.process)
            self.wait(5)
            if self._job is not None:
                self._job.wait_empty()
                self._job.close()
            self._api.close_handle(self._info.process)
            self.closed = True


class AppContainer:
    """An AppContainer profile and the commands started in it, used by windows_runtime.

    Without a name the profile is unique and deleted on close. A named profile is
    persistent: windows_runtime keeps one per workspace so its file grants are made
    once, and close only reaps commands. Capabilities are SID strings that every
    command token must carry exactly. Thread-confined.
    """

    def __init__(self, name=None, capabilities=()):
        self._api = _Win32()
        self.persistent = name is not None
        self.name = name or "Eirene.Sandbox." + uuid.uuid4().hex
        self._sid = self._api.profile(self.name)
        self._capabilities = []
        self._processes = []
        self.closed = False
        try:
            if capabilities:
                self._capabilities = self._api.capability_sids(capabilities)
            self.home = self._api.folder(self._sid) / "LocalState"
            self.home.mkdir(exist_ok=True)
        except BaseException:
            self._release()
            raise

    @property
    def sid(self):
        return self._api.sid_string(self._sid)

    def spawn(self, argv, *, cwd=None, env=None, std_handles=None, temp=None):
        if self.closed:
            raise ToolError("AppContainer profile is closed")
        _command_line(argv)  # Validate before allocating any process resources.
        argv = tuple(argv)
        system_root = os.environ.get("SystemRoot")
        if not system_root or not Path(system_root).is_absolute():
            raise ToolError("AppContainer requires an absolute SystemRoot")
        options = {"std_handles": std_handles} if std_handles else {}
        if self._capabilities:
            options["capabilities"] = self._capabilities
        info = self._api.suspended(argv, cwd or self.home,
                                   _environment(system_root, self.home, os.environ.get("LOCALAPPDATA", ""), env, temp),
                                   self._sid, **options)
        process = Process(self._api, info)
        # Retain ownership even when cleanup itself fails, so close() can retry.
        self._processes.append(process)
        try:
            self._api.verify(info.process, self._sid, *([self._capabilities] if self._capabilities else []))
            process._job = self._api.attach(info.pid)
            self._api.resume(info.thread)
        except BaseException:
            # Kill before closing handles, even if token validation/Job assignment failed.
            process.close()
            raise
        finally:
            self._api.close_handle(info.thread)
        return process

    def close(self):
        if not self.closed:
            for process in self._processes:
                process.close()
            self._release()
            self.closed = True

    def _release(self):
        if self._capabilities:
            self._api.free_capabilities(self._capabilities)
        self._capabilities = []
        if self.persistent:
            self._api.free_sid(self._sid)
        else:
            self._api.remove_profile(self.name, self._sid)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.close()
