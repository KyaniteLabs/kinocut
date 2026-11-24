"""Directory anchoring and native exclusive renames."""

from __future__ import annotations

import contextlib
import ctypes
import errno
import os
import stat
import sys

from ..errors import MCPVideoError
from ._windows import lock_directory_ancestry, windows_supported


def _unsafe(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="unsafe_path")


def _partial_output(message: str) -> MCPVideoError:
    return MCPVideoError(
        message,
        error_type="processing_error",
        code="partial_output_publication",
        suggested_action={"action": "inspect_output", "prior_output_preserved": False},
    )


def _open_root_descriptor() -> int:
    """Open the filesystem root as an anchor descriptor.

    ``O_PATH`` is requested because hardened hosts (seccomp/LSM policies, some
    container runtimes) deny opening ``/`` with read permission. A read-open
    of the root is not needed to walk the ancestry: every component below it
    is opened with ``O_NOFOLLOW`` relative to the parent descriptor, and
    ``O_PATH`` descriptors are valid ``dir_fd`` arguments. Without this
    fallback the whole atomic-publication path fails on such hosts with
    "Atomic output could not preserve directory identity: PermissionError".
    """
    try:
        return os.open(os.path.sep, os.O_RDONLY | os.O_DIRECTORY)
    except PermissionError:
        if not hasattr(os, "O_PATH"):
            raise
        return os.open(os.path.sep, os.O_PATH | os.O_DIRECTORY)


def _open_directory(directory: str) -> int:
    """Walk canonical ancestry without following a concurrently planted symlink."""
    descriptor = _open_root_descriptor()
    try:
        for component in directory.split(os.path.sep):
            if not component:
                continue
            try:
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            except FileNotFoundError:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(component, mode=0o755, dir_fd=descriptor)
                # A concurrent creator must still pass the no-follow open.
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


class _Directory:
    def __init__(self, path: str):
        self.path, self.fd, self.close_windows = path, None, None
        if os.name == "posix" and hasattr(os, "O_NOFOLLOW") and os.open in os.supports_dir_fd:
            self.fd = _open_directory(path)
        elif windows_supported():
            self.close_windows = lock_directory_ancestry(path)
        else:
            raise _unsafe("Atomic publication requires supported directory anchoring")
        try:
            self.identity = os.fstat(self.fd) if self.fd is not None else os.stat(path)
        except BaseException:
            self.close()
            raise

    def check(self):
        current = os.stat(self.path, follow_symlinks=False)
        if not stat.S_ISDIR(current.st_mode) or (current.st_dev, current.st_ino) != (
            self.identity.st_dev,
            self.identity.st_ino,
        ):
            raise _unsafe("Output directory changed during publication")

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        if self.close_windows is not None:
            self.close_windows()
            self.close_windows = None

    def options(self):
        return {"dir_fd": self.fd} if self.fd is not None else {}

    def name(self, basename):
        return basename if self.fd is not None else os.path.join(self.path, basename)


def _rename_exclusive(anchor: _Directory, source: str, destination: str, *, exchange: bool = False) -> None:
    """Rename without replacing a rival, or atomically exchange two entries."""
    if os.name == "nt":
        if exchange:
            raise OSError(errno.ENOTSUP, "Atomic directory exchange is unavailable")
        os.rename(anchor.name(source), anchor.name(destination))
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "linux":
        rename = getattr(libc, "renameat2", None)
        flags = 2 if exchange else 1  # RENAME_EXCHANGE / RENAME_NOREPLACE
    elif sys.platform == "darwin":
        rename = getattr(libc, "renameatx_np", None)
        flags = 2 if exchange else 4  # RENAME_SWAP / RENAME_EXCL
    else:
        rename = None
    if rename is None or anchor.fd is None:
        raise OSError(errno.ENOTSUP, "Exclusive rename is unavailable")
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    if rename(anchor.fd, os.fsencode(source), anchor.fd, os.fsencode(destination), flags) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def _same_inode(first: os.stat_result, second: os.stat_result) -> bool:
    return (first.st_dev, first.st_ino) == (second.st_dev, second.st_ino)
