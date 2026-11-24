"""Edit-session lock integration with the Windows byte-range backend."""

import os
from types import SimpleNamespace

import pytest

from kinocut.projectstore import _filelock
from kinocut.te.edit_session import _session_lock


def test_session_lock_uses_windows_backend_and_releases_on_failure(tmp_path, monkeypatch):
    calls = []

    def locking(fd, mode, length):
        calls.append((fd, mode, length, os.lseek(fd, 0, os.SEEK_CUR)))

    monkeypatch.setattr(_filelock, "_HAVE_FCNTL", False)
    monkeypatch.setattr(_filelock, "msvcrt", SimpleNamespace(LK_LOCK=1, LK_UNLCK=2, locking=locking), raising=False)
    path = tmp_path / "session.json"
    with pytest.raises(RuntimeError, match="cancelled"), _session_lock(path):
        assert len(calls) == 1
        raise RuntimeError("cancelled")
    descriptor, *_ = calls[0]
    assert calls == [(descriptor, 1, 1, 0), (descriptor, 2, 1, 0)]
    assert (tmp_path / ".session.lock").is_file()
    with pytest.raises(OSError):
        os.fstat(descriptor)
