"""Windows Job Object ownership established before a child can execute."""

from __future__ import annotations

import ctypes
import time
from ctypes import c_int32, c_uint32, c_uint64, c_size_t, c_void_p

from .defaults import DEFAULT_RENDER_STOP_POLL_INTERVAL, DEFAULT_RENDER_STOP_TIMEOUT
from .errors import MCPVideoError


CREATE_SUSPENDED = 0x00000004


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", c_uint32),
        ("minimum_working_set", c_size_t),
        ("maximum_working_set", c_size_t),
        ("active_process_limit", c_uint32),
        ("affinity", c_size_t),
        ("priority", c_uint32),
        ("scheduling", c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, c_uint64) for name in ("read_ops", "write_ops", "other_ops", "read", "write", "other")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("basic", _BasicLimits),
        ("io", _IoCounters),
        ("process_memory", c_size_t),
        ("job_memory", c_size_t),
        ("peak_process_memory", c_size_t),
        ("peak_job_memory", c_size_t),
    ]


class _Accounting(ctypes.Structure):
    _fields_ = [
        ("user_time", ctypes.c_int64),
        ("kernel_time", ctypes.c_int64),
        ("period_user_time", ctypes.c_int64),
        ("period_kernel_time", ctypes.c_int64),
        ("faults", c_uint32),
        ("total_processes", c_uint32),
        ("active_processes", c_uint32),
        ("terminated_processes", c_uint32),
    ]


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", c_uint32),
        ("usage", c_uint32),
        ("thread_id", c_uint32),
        ("owner_pid", c_uint32),
        ("base_priority", c_int32),
        ("delta_priority", c_int32),
        ("flags", c_uint32),
    ]


def _ownership_error():
    return MCPVideoError(
        "Windows child process ownership could not be established", code="process_ownership_unavailable"
    )


def _kernel():
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateJobObjectW": ([c_void_p, ctypes.c_wchar_p], c_void_p),
        "SetInformationJobObject": ([c_void_p, c_int32, c_void_p, c_uint32], c_int32),
        "AssignProcessToJobObject": ([c_void_p, c_void_p], c_int32),
        "TerminateJobObject": ([c_void_p, c_uint32], c_int32),
        "QueryInformationJobObject": ([c_void_p, c_int32, c_void_p, c_uint32, c_void_p], c_int32),
        "CreateToolhelp32Snapshot": ([c_uint32, c_uint32], c_void_p),
        "Thread32First": ([c_void_p, ctypes.POINTER(_ThreadEntry)], c_int32),
        "Thread32Next": ([c_void_p, ctypes.POINTER(_ThreadEntry)], c_int32),
        "OpenThread": ([c_uint32, c_int32, c_uint32], c_void_p),
        "ResumeThread": ([c_void_p], c_uint32),
        "CloseHandle": ([c_void_p], c_int32),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


class WindowsJob:
    """Kill-on-close job; attach and resume a CREATE_SUSPENDED owned child."""

    def __init__(self, kernel=None):
        self.kernel = kernel or _kernel()
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise _ownership_error()
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway permission.
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise _ownership_error()

    def attach(self, process):
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise _ownership_error()
        self._resume_primary(process.pid)

    def _resume_primary(self, pid):
        snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
        if not snapshot or snapshot == c_void_p(-1).value:
            raise _ownership_error()
        try:
            entry = _ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            ready, matches = self.kernel.Thread32First(snapshot, ctypes.byref(entry)), []
            while ready:
                if entry.owner_pid == pid:
                    matches.append(entry.thread_id)
                ready = self.kernel.Thread32Next(snapshot, ctypes.byref(entry))
            if len(matches) != 1:
                raise _ownership_error()
            self._resume_thread(matches[0])
        finally:
            self.kernel.CloseHandle(snapshot)

    def _resume_thread(self, thread_id):
        thread = self.kernel.OpenThread(2, False, thread_id)  # THREAD_SUSPEND_RESUME
        if not thread:
            raise _ownership_error()
        try:
            if self.kernel.ResumeThread(thread) != 1:
                raise _ownership_error()
        finally:
            self.kernel.CloseHandle(thread)

    def stop(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise _ownership_error()
        deadline = time.monotonic() + DEFAULT_RENDER_STOP_TIMEOUT
        while True:
            accounting = _Accounting()
            if not self.kernel.QueryInformationJobObject(
                self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None
            ):
                raise _ownership_error()
            if not accounting.active_processes:
                return
            if time.monotonic() >= deadline:
                raise MCPVideoError("Windows process job did not quiesce", code="process_cleanup_failed")
            time.sleep(DEFAULT_RENDER_STOP_POLL_INTERVAL)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
