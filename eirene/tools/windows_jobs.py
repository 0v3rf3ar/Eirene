"""Windows process ownership using documented Job/Toolhelp APIs.

The child starts suspended; assignment must succeed before its first instruction.
Only imported on Windows. Python orchestrates the OS; it does not execute commands.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes as W

K = ctypes.WinDLL("kernel32", use_last_error=True)
SIZE = ctypes.c_size_t


class BASIC(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_longlong),
        ("job_time", ctypes.c_longlong),
        ("flags", W.DWORD),
        ("min_ws", SIZE),
        ("max_ws", SIZE),
        ("active", W.DWORD),
        ("affinity", SIZE),
        ("priority", W.DWORD),
        ("scheduling", W.DWORD),
    ]


class IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_ulonglong)
        for name in (
            "reads",
            "writes",
            "others",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class LIMITS(ctypes.Structure):
    _fields_ = [
        ("basic", BASIC),
        ("io", IO),
        ("process_memory", SIZE),
        ("job_memory", SIZE),
        ("peak_process", SIZE),
        ("peak_job", SIZE),
    ]


class THREAD(ctypes.Structure):
    _fields_ = [
        ("size", W.DWORD),
        ("usage", W.DWORD),
        ("id", W.DWORD),
        ("owner", W.DWORD),
        ("base", W.LONG),
        ("delta", W.LONG),
        ("flags", W.DWORD),
    ]


def api(name, result, args):
    function = getattr(K, name)
    function.restype = result
    function.argtypes = args
    return function


create_job = api("CreateJobObjectW", W.HANDLE, [ctypes.c_void_p, W.LPCWSTR])
set_limits = api(
    "SetInformationJobObject",
    W.BOOL,
    [W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD],
)
open_process = api("OpenProcess", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
assign = api("AssignProcessToJobObject", W.BOOL, [W.HANDLE, W.HANDLE])
close = api("CloseHandle", W.BOOL, [W.HANDLE])
terminate = api("TerminateJobObject", W.BOOL, [W.HANDLE, W.UINT])
snapshot = api("CreateToolhelp32Snapshot", W.HANDLE, [W.DWORD, W.DWORD])
first = api("Thread32First", W.BOOL, [W.HANDLE, ctypes.POINTER(THREAD)])
next_thread = api("Thread32Next", W.BOOL, [W.HANDLE, ctypes.POINTER(THREAD)])
open_thread = api("OpenThread", W.HANDLE, [W.DWORD, W.BOOL, W.DWORD])
resume = api("ResumeThread", W.DWORD, [W.HANDLE])


class Job:
    def __init__(self, handle):
        self.handle = handle

    def terminate(self):
        if self.handle:
            terminate(self.handle, 1)

    def close(self):
        if self.handle:
            close(self.handle)
            self.handle = None


def own(pid: int) -> Job:
    job = Job(create_job(None, None))
    if not job.handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits = LIMITS()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not set_limits(job.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        process = open_process(0x0100 | 0x0001, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not assign(job.handle, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            close(process)
        snap = snapshot(0x00000004, 0)  # TH32CS_SNAPTHREAD
        if snap == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = THREAD()
            entry.size = ctypes.sizeof(entry)
            found = first(snap, ctypes.byref(entry))
            while found:
                if entry.owner == pid:
                    thread = open_thread(0x0002, False, entry.id)
                    if not thread:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        if resume(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        close(thread)
                    return job
                found = next_thread(snap, ctypes.byref(entry))
            raise OSError("cannot find suspended command thread")
        finally:
            close(snap)
    except BaseException:
        job.close()
        raise
