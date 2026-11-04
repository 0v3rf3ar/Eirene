"""Does this Windows account hold the "log on as a batch job" right?

Signed-out (S4U) routines start through a batch logon. Without the right,
Windows can accept the task and then never start it, so check before offering.
"""

from __future__ import annotations

import sys

BATCH = "SeBatchLogonRight"
DENY_BATCH = "SeDenyBatchLogonRight"


def elevated() -> bool:
    """True when this process runs with an administrator token (Run as administrator)."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, AttributeError):
        return False


def password_changed_at() -> float | None:
    """When this account's password was last set (local accounts), or None."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        import getpass
        import time
        from ctypes import wintypes

        class USER_INFO_1(ctypes.Structure):
            _fields_ = [("name", wintypes.LPWSTR), ("password", wintypes.LPWSTR),
                        ("password_age", wintypes.DWORD), ("priv", wintypes.DWORD),
                        ("home_dir", wintypes.LPWSTR), ("comment", wintypes.LPWSTR),
                        ("flags", wintypes.DWORD), ("script_path", wintypes.LPWSTR)]

        netapi = ctypes.WinDLL("netapi32")
        netapi.NetUserGetInfo.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                          ctypes.POINTER(ctypes.c_void_p)]
        netapi.NetUserGetInfo.restype = wintypes.DWORD
        netapi.NetApiBufferFree.argtypes = [ctypes.c_void_p]
        buffer = ctypes.c_void_p()
        if netapi.NetUserGetInfo(None, getpass.getuser(), 1, ctypes.byref(buffer)) != 0:
            return None
        try:
            age = ctypes.cast(buffer, ctypes.POINTER(USER_INFO_1)).contents.password_age
        finally:
            netapi.NetApiBufferFree(buffer)
        return time.time() - age
    except (OSError, AttributeError, ValueError):
        return None


def batch_logon_allowed() -> bool | None:
    """True or False when the rights could be read; None when it cannot tell."""
    if sys.platform != "win32":
        return None
    try:
        rights = _account_rights()
    except OSError:
        return None
    if rights is None:
        return None
    return BATCH in rights and DENY_BATCH not in rights


def _account_rights() -> set[str] | None:
    """Rights granted to the user's SID and every group SID in its token."""
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    class LSA_UNICODE_STRING(ctypes.Structure):
        _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                    ("Buffer", wintypes.LPWSTR)]

    class LSA_OBJECT_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Length", wintypes.ULONG), ("RootDirectory", wintypes.HANDLE),
                    ("ObjectName", ctypes.c_void_p), ("Attributes", wintypes.ULONG),
                    ("SecurityDescriptor", ctypes.c_void_p),
                    ("SecurityQualityOfService", ctypes.c_void_p)]

    class SID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    TOKEN_QUERY = 0x0008
    TOKEN_USER, TOKEN_GROUPS = 1, 2
    POLICY_LOOKUP_NAMES = 0x00000800
    STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034

    advapi.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                        ctypes.POINTER(wintypes.HANDLE)]
    advapi.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                           wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    advapi.LsaOpenPolicy.argtypes = [ctypes.c_void_p, ctypes.POINTER(LSA_OBJECT_ATTRIBUTES),
                                     wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi.LsaOpenPolicy.restype = wintypes.ULONG
    advapi.LsaEnumerateAccountRights.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p,
        ctypes.POINTER(ctypes.POINTER(LSA_UNICODE_STRING)), ctypes.POINTER(wintypes.ULONG)]
    advapi.LsaEnumerateAccountRights.restype = wintypes.ULONG
    advapi.LsaFreeMemory.argtypes = [ctypes.c_void_p]
    advapi.LsaClose.argtypes = [wintypes.HANDLE]
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]

    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(kernel.GetCurrentProcess(), TOKEN_QUERY,
                                   ctypes.byref(token)):
        return None

    def info(kind: int):
        size = wintypes.DWORD()
        advapi.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
        if not size.value:
            return None
        buffer = ctypes.create_string_buffer(size.value)
        if not advapi.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)):
            return None
        return buffer

    try:
        user = info(TOKEN_USER)
        groups = info(TOKEN_GROUPS)
        if user is None or groups is None:
            return None
        # Deny-only groups count too: UAC filters Administrators to deny-only in a
        # normal session, but the S4U logon that runs the routine gets it back.
        sids = [SID_AND_ATTRIBUTES.from_buffer(user).Sid]
        count = wintypes.DWORD.from_buffer(groups).value
        offset = ctypes.sizeof(ctypes.c_void_p)  # DWORD count, padded to pointer size
        entries = (SID_AND_ATTRIBUTES * count).from_buffer(groups, offset)
        sids.extend(entry.Sid for entry in entries)

        policy = wintypes.HANDLE()
        attributes = LSA_OBJECT_ATTRIBUTES()
        attributes.Length = ctypes.sizeof(LSA_OBJECT_ATTRIBUTES)
        if advapi.LsaOpenPolicy(None, ctypes.byref(attributes), POLICY_LOOKUP_NAMES,
                                ctypes.byref(policy)) != 0:
            return None
        rights: set[str] = set()
        try:
            for sid in sids:
                found = ctypes.POINTER(LSA_UNICODE_STRING)()
                total = wintypes.ULONG()
                status = advapi.LsaEnumerateAccountRights(policy, sid, ctypes.byref(found),
                                                          ctypes.byref(total))
                if status == STATUS_OBJECT_NAME_NOT_FOUND:
                    continue
                if status != 0:
                    return None
                try:
                    for index in range(total.value):
                        item = found[index]
                        rights.add(ctypes.wstring_at(item.Buffer, item.Length // 2))
                finally:
                    advapi.LsaFreeMemory(found)
        finally:
            advapi.LsaClose(policy)
        return rights
    finally:
        kernel.CloseHandle(token)
