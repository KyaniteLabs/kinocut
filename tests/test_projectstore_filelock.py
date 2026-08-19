"""Cross-platform error-contract tests for the portable projectstore lock (#451).

The Windows backend is exercised on POSIX by flipping the call-time backend
flag and injecting a fake ``msvcrt`` module, so the contract — permanent errors
raise promptly, only genuine contention waits or maps to ``BlockingIOError`` —
is enforced on every platform, not just Windows.
"""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest

import kinocut.projectstore._filelock as filelock


class _FakeMsvcrt:
    """msvcrt.locking stand-in scripted per test."""

    LK_LOCK = 1
    LK_NBLCK = 2
    LK_UNLCK = 3

    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self._outcomes = list(outcomes)
        self.calls: list[tuple[int, int]] = []
        self.seen_byte_counts: list[int] = []
        self.seen_entry_offsets: list[int] = []

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        self.calls.append((fd, mode))
        self.seen_byte_counts.append(nbytes)
        self.seen_entry_offsets.append(os.lseek(fd, 0, os.SEEK_CUR))
        outcome = self._outcomes.pop(0) if self._outcomes else None
        if outcome is not None:
            raise outcome


@pytest.fixture()
def windows_backend(monkeypatch, tmp_path: Path):
    """Force the Windows code path with a scriptable msvcrt lock primitive."""

    def install(outcomes: list[BaseException | None]) -> _FakeMsvcrt:
        fake = _FakeMsvcrt(outcomes)
        monkeypatch.setattr(filelock, "_HAVE_FCNTL", False)
        monkeypatch.setattr(filelock, "msvcrt", fake, raising=False)
        return fake

    return install


class TestWindowsBlockingContract:
    def test_permanent_error_raises_promptly(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        windows_backend([OSError(errno.EBADF, "bad descriptor")])
        with lease.open("a+b") as handle, pytest.raises(OSError) as excinfo:
            filelock.lock_exclusive(handle, blocking=True)
        assert excinfo.value.errno == errno.EBADF

    def test_permission_error_is_permanent_not_hang(self, windows_backend, tmp_path):
        # EACCES is contention on Windows locking; a permissions failure there
        # surfaces as EPERM, which must raise instead of retrying forever.
        lease = tmp_path / "lease"
        lease.touch()
        fake = windows_backend([OSError(errno.EPERM, "permission denied")])
        with lease.open("a+b") as handle, pytest.raises(OSError) as excinfo:
            filelock.lock_exclusive(handle, blocking=True)
        assert excinfo.value.errno == errno.EPERM
        assert len(fake.calls) == 1

    def test_contention_retries_until_acquired(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        fake = windows_backend(
            [
                OSError(errno.EACCES, "contention"),
                OSError(errno.EDEADLK, "deadlock"),
                None,  # third attempt succeeds
            ]
        )
        with lease.open("a+b") as handle:
            filelock.lock_exclusive(handle, blocking=True)
        assert len(fake.calls) == 3

    def test_unlock_runs_unlock_mode(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        fake = windows_backend([None])
        with lease.open("a+b") as handle:
            filelock.unlock(handle)
        assert fake.calls[0][1] == _FakeMsvcrt.LK_UNLCK
        # cross-participant agreement: exactly one byte, locked at offset 0
        assert fake.seen_byte_counts == [filelock._LOCK_BYTES]
        assert fake.seen_entry_offsets == [0]


class TestWindowsNonBlockingContract:
    def test_contention_maps_to_blockingioerror(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        windows_backend([OSError(errno.EACCES, "contention")])
        with lease.open("a+b") as handle, pytest.raises(BlockingIOError):
            filelock.lock_exclusive(handle, blocking=False)

    def test_deadlock_maps_to_blockingioerror(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        windows_backend([OSError(errno.EDEADLK, "deadlock")])
        with lease.open("a+b") as handle, pytest.raises(BlockingIOError):
            filelock.lock_exclusive(handle, blocking=False)

    def test_permanent_error_propagates_untranslated(self, windows_backend, tmp_path):
        lease = tmp_path / "lease"
        lease.touch()
        fake = windows_backend([OSError(errno.EBADF, "bad descriptor")])
        with lease.open("a+b") as handle, pytest.raises(OSError) as excinfo:
            filelock.lock_exclusive(handle, blocking=False)
        assert not isinstance(excinfo.value, BlockingIOError)
        assert excinfo.value.errno == errno.EBADF
        assert len(fake.calls) == 1


@pytest.mark.skipif(not hasattr(filelock, "fcntl"), reason="POSIX backend not importable on this platform")
class TestPosixBackendUnchanged:
    def test_dispatch_uses_posix_when_fcntl_present(self, monkeypatch, tmp_path):
        monkeypatch.setattr(filelock, "_HAVE_FCNTL", True)
        lease = tmp_path / "lease"
        lease.touch()
        calls: list[tuple[int, int]] = []
        real_flock = filelock.fcntl.flock

        def spy_flock(fd, flags):
            calls.append((fd, flags))
            return real_flock(fd, flags)

        monkeypatch.setattr(filelock.fcntl, "flock", spy_flock)
        with lease.open("a+b") as handle:
            filelock.lock_exclusive(handle, blocking=False)
        assert calls, "POSIX backend must be dispatched when _HAVE_FCNTL is true"
