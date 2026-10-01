"""Anchor Windows ancestry and reject observed reparse points during publication."""

from __future__ import annotations

import os
import contextlib
from pathlib import Path

from .errors import MCPVideoError


def lock_directory_ancestry(directory: str):
    """Return closeable handles; omit DELETE sharing so directories cannot move."""
    import ctypes
    from ctypes import wintypes

    class FileInfo(ctypes.Structure):
        _fields_ = [
            ("attributes", wintypes.DWORD),
            ("created", wintypes.FILETIME),
            ("accessed", wintypes.FILETIME),
            ("written", wintypes.FILETIME),
            ("volume", wintypes.DWORD),
            ("size_high", wintypes.DWORD),
            ("size_low", wintypes.DWORD),
            ("links", wintypes.DWORD),
            ("index_high", wintypes.DWORD),
            ("index_low", wintypes.DWORD),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create.restype = wintypes.HANDLE
    info = kernel.GetFileInformationByHandle
    info.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInfo)]
    info.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes, close.restype = [wintypes.HANDLE], wintypes.BOOL
    handles = []
    paths = [*reversed(Path(directory).parents), Path(directory)]
    try:
        for path in paths:
            # Parent handles deny DELETE sharing. Create only the next component,
            # then check it without following reparse points before its children.
            # Publication still requires exclusive destination-writer ownership.
            if not path.exists():
                with contextlib.suppress(FileExistsError):
                    os.mkdir(path)
            handle = create(str(path), 0x80, 0x3, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            details = FileInfo()
            if not info(handle, ctypes.byref(details)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not details.attributes & 0x10 or details.attributes & 0x400:
                raise MCPVideoError("Output ancestry contains a reparse point", code="unsafe_path")
    except BaseException:
        for handle in reversed(handles):
            close(handle)
        raise
    return lambda: [close(handle) for handle in reversed(handles)]


def windows_supported() -> bool:
    return os.name == "nt"
