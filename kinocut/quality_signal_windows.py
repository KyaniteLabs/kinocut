"""Cancellable anonymous-pipe reads on Windows; no descendant ownership claim."""

import ctypes
from ctypes import wintypes
import os

from .defaults import DEFAULT_RENDER_STOP_POLL_INTERVAL
from .limits import MAX_QUALITY_SIGNALSTATS_LINE_BYTES
from .errors import MCPVideoError


def _available_bytes(pipe):
    # This API is lazy: importing quality analysis on POSIX must stay portable.
    import msvcrt

    available = wintypes.DWORD()
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    peek = kernel.PeekNamedPipe
    peek.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    peek.restype = wintypes.BOOL
    if not peek(msvcrt.get_osfhandle(pipe.fileno()), None, 0, None, ctypes.byref(available), None):
        if ctypes.get_last_error() in {109, 233}:  # broken/disconnected pipe = EOF
            return -1
        raise MCPVideoError("Signalstats pipe unavailable", code="analysis_invalid_output")
    return available.value


def chunks(pipe, stop, size):
    while not stop.is_set():
        ready = _available_bytes(pipe)
        if ready < 0:
            return
        if ready:
            data = os.read(pipe.fileno(), min(size, ready))
            if not data:
                return
            yield data
        else:
            stop.wait(DEFAULT_RENDER_STOP_POLL_INTERVAL)


def lines(pipe, stop):
    pending = bytearray()
    for chunk in chunks(pipe, stop, MAX_QUALITY_SIGNALSTATS_LINE_BYTES + 1):
        pending.extend(chunk)
        while (newline := pending.find(b"\n")) >= 0:
            line = bytes(pending[: newline + 1])
            del pending[: newline + 1]
            yield line
        if len(pending) > MAX_QUALITY_SIGNALSTATS_LINE_BYTES:
            raise MCPVideoError("Signalstats line budget exceeded", code="analysis_over_limit")
    if pending and not stop.is_set():
        yield bytes(pending)
