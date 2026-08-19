"""Portable exclusive file locking for the project store leases.

``fcntl`` is a POSIX kernel API. Windows has no equivalent and no installable
shim, so importing it at module scope made the whole ``projectstore`` package —
and therefore ``kino --mcp`` — unimportable on Windows. ``msvcrt.locking``
provides byte-range locking, which is enough for the whole-file advisory leases
used here: every participant locks the same single byte of the same lease file.

The two backends are kept behaviourally identical so callers need no platform
branches (#451 enforces this with cross-platform contract tests):

- ``lock_exclusive(handle)`` blocks until the lock is acquired, retrying only
  while the error signals genuine contention (the two Windows locking-contention
  errnos). Permanent errors — bad descriptor, permissions, unreadable file —
  propagate promptly so a broken lease fails loudly instead of hanging.
- ``lock_exclusive(handle, blocking=False)`` raises :class:`BlockingIOError`
  when another holder has it; contention errnos are normalised to that signal
  and every other error surfaces untranslated.
- ``unlock(handle)`` releases it.

Both accept either a raw file descriptor or any object with ``fileno()``,
matching the mix already present in the store (``os.open`` in ``store`` versus
``Path.open`` in the render job modules).

Backend selection happens at call time (``_HAVE_FCNTL``) rather than import
time so the Windows contract is testable on POSIX by flipping the flag and
injecting a fake ``msvcrt`` — the property "behaviourally identical" is a
checked property, not a promise.
"""

from __future__ import annotations

import errno
import os
from typing import IO

try:  # POSIX
    import fcntl

    _HAVE_FCNTL = True
except ImportError:  # Windows
    import msvcrt

    _HAVE_FCNTL = False

# msvcrt locks a byte range rather than the whole file. One byte at offset 0 is
# sufficient and is what every participant agrees to lock.
_LOCK_BYTES = 1

# The only errnos msvcrt.locking raises for genuine lock contention, per the
# Windows locking documentation (EACCES: region already locked; EDEADLK: would
# deadlock). Everything else — EBADF, EPERM, EINVAL, ... — is permanent.
_WINDOWS_CONTENTION_ERRNOS = frozenset({errno.EACCES, errno.EDEADLK})

Lockable = int | IO[bytes]


def _descriptor(handle: Lockable) -> int:
    return handle if isinstance(handle, int) else handle.fileno()


def _is_windows_contention(exc: OSError) -> bool:
    return exc.errno in _WINDOWS_CONTENTION_ERRNOS


def _lock_exclusive_posix(handle: Lockable, *, blocking: bool) -> None:
    flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
    fcntl.flock(_descriptor(handle), flags)


def _unlock_posix(handle: Lockable) -> None:
    fcntl.flock(_descriptor(handle), fcntl.LOCK_UN)


def _at_offset_zero(fd: int, mode: int) -> None:
    """Run one msvcrt lock operation at offset 0, restoring the position."""
    previous = os.lseek(fd, 0, os.SEEK_CUR)
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        msvcrt.locking(fd, mode, _LOCK_BYTES)
    finally:
        os.lseek(fd, previous, os.SEEK_SET)


def _lock_exclusive_windows(handle: Lockable, *, blocking: bool) -> None:
    fd = _descriptor(handle)
    if not blocking:
        try:
            _at_offset_zero(fd, msvcrt.LK_NBLCK)
        except OSError as exc:
            # flock signals contention with BlockingIOError; msvcrt uses a
            # bare OSError for it. Callers catch BlockingIOError, so translate
            # contention only — permanent errors surface untranslated.
            if not _is_windows_contention(exc):
                raise
            raise BlockingIOError(exc.errno, exc.strerror) from exc
        return

    # LK_LOCK retries ten times at one-second intervals and then gives up,
    # while the POSIX blocking contract waits indefinitely. Loop so the
    # blocking contract holds — but only across genuine contention, so a
    # permanently broken lease raises instead of hanging forever.
    while True:
        try:
            _at_offset_zero(fd, msvcrt.LK_LOCK)
            return
        except OSError as exc:
            if not _is_windows_contention(exc):
                raise
            continue


def _unlock_windows(handle: Lockable) -> None:
    _at_offset_zero(_descriptor(handle), msvcrt.LK_UNLCK)


def lock_exclusive(handle: Lockable, *, blocking: bool = True) -> None:
    """Acquire the exclusive lease lock; block until held unless ``blocking=False``."""
    if _HAVE_FCNTL:
        _lock_exclusive_posix(handle, blocking=blocking)
    else:
        _lock_exclusive_windows(handle, blocking=blocking)


def unlock(handle: Lockable) -> None:
    """Release the exclusive lease lock."""
    if _HAVE_FCNTL:
        _unlock_posix(handle)
    else:
        _unlock_windows(handle)
