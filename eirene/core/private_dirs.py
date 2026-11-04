"""Folders only this user can open, whether Eirene runs elevated or not.

CPython 3.12.4+ turns mkdir(mode=0o700) on Windows into a protected DACL for SYSTEM,
Administrators and the *owner* (CVE-2024-4030). An elevated process's owner is the
Administrators group, so a folder made while running as administrator locks the
same user out once they run Eirene normally. Name the user's SID instead.
"""

from __future__ import annotations

import os
from pathlib import Path


def make_private_dir(path: Path, *, parents: bool = False) -> None:
    """Create path (if missing) readable only by this user."""
    path = Path(path)
    if os.name != "nt":
        path.mkdir(mode=0o700, parents=parents, exist_ok=True)
        return
    if path.is_dir():
        return
    if parents:
        path.parent.mkdir(parents=True, exist_ok=True)
    sid = _user_sid()
    if sid is None:
        path.mkdir(mode=0o700, exist_ok=True)
        return
    try:
        _create(path, f"D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;{sid})")
    except FileExistsError:
        if not path.is_dir():
            raise


def _user_sid() -> str | None:
    import ctypes
    from ctypes import wintypes
    try:
        advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    except OSError:
        return None
    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.ConvertSidToStringSidW.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        return None
    try:
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value or 1)
        if not advapi.GetTokenInformation(token, 1, buffer, size, ctypes.byref(size)):
            return None
        sid = ctypes.c_void_p.from_buffer(buffer).value  # TOKEN_USER.User.Sid
        text = wintypes.LPWSTR()
        if not advapi.ConvertSidToStringSidW(sid, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            kernel.LocalFree(text)
    finally:
        kernel.CloseHandle(token)


def _create(path: Path, sddl: str) -> None:
    import ctypes
    from ctypes import wintypes

    class Attributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                    ("inherit", wintypes.BOOL)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                        ctypes.c_void_p]
    kernel.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not convert(sddl, 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        attributes = Attributes(ctypes.sizeof(Attributes), descriptor, False)
        if not kernel.CreateDirectoryW(str(path), ctypes.byref(attributes)):
            error = ctypes.get_last_error()
            if error == 183:  # ERROR_ALREADY_EXISTS
                raise FileExistsError(str(path))
            raise OSError(None, ctypes.FormatError(error), str(path), error)
    finally:
        kernel.LocalFree(descriptor)
