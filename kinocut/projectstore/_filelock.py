"""Portable exclusive file locking for the project store leases.

``fcntl`` is a POSIX kernel API. Windows has no equivalent and no installable
shim, so importing it at module scope made the whole ``projectstore`` package —
and therefore ``kino --mcp`` — unimportable on Windows. ``msvcrt.locking``
provides byte-range locking, which is enough for the whole-file advisory leases
used here: every participant locks the same single byte of the same lease file.

The two backends are kept behaviourally identical so callers need no platform
branches:

- ``lock_exclusive(handle)`` blocks until the lock is acquired.
- ``lock_exclusive(handle, blocking=False)`` raises :class:`BlockingIOError`
  when another holder has it. ``flock`` does this natively; ``msvcrt`` raises a
  plain ``OSError``, so it is normalised here.
- ``unlock(handle)`` releases it.

Both accept either a raw file descriptor or any object with ``fileno()``,
matching the mix already present in the store (``os.open`` in ``store`` versus
``Path.open`` in the render job modules).
"""

from __future__ import annotations

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

Lockable = int | IO[bytes]


def _descriptor(handle: Lockable) -> int:
    return handle if isinstance(handle, int) else handle.fileno()


if _HAVE_FCNTL:

    def lock_exclusive(handle: Lockable, *, blocking: bool = True) -> None:
        flags = fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB
        fcntl.flock(_descriptor(handle), flags)

    def unlock(handle: Lockable) -> None:
        fcntl.flock(_descriptor(handle), fcntl.LOCK_UN)

else:

    def _at_offset_zero(fd: int, mode: int) -> None:
        """Run one msvcrt lock operation at offset 0, restoring the position."""
        previous = os.lseek(fd, 0, os.SEEK_CUR)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, mode, _LOCK_BYTES)
        finally:
            os.lseek(fd, previous, os.SEEK_SET)

    def lock_exclusive(handle: Lockable, *, blocking: bool = True) -> None:
        fd = _descriptor(handle)
        if not blocking:
            try:
                _at_offset_zero(fd, msvcrt.LK_NBLCK)
            except OSError as exc:
                # flock signals contention with BlockingIOError; msvcrt uses a
                # bare OSError. Callers catch BlockingIOError, so translate.
                raise BlockingIOError(exc.errno, exc.strerror) from exc
            return

        # LK_LOCK retries ten times at one-second intervals and then gives up,
        # while LOCK_EX waits indefinitely. Loop so the blocking contract holds.
        while True:
            try:
                _at_offset_zero(fd, msvcrt.LK_LOCK)
                return
            except OSError:
                continue

    def unlock(handle: Lockable) -> None:
        _at_offset_zero(_descriptor(handle), msvcrt.LK_UNLCK)
