"""O(1) crash-safe WAL append and recovery helpers for :mod:`kinocut.projectstore.store`."""

from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
import tempfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error

# Above this threshold, appends use an O(1) crash-safe WAL + direct append so
# growing record logs never incur quadratic full-file copying on every write.
_DIRECT_APPEND_THRESHOLD = 4096


def _canonical_wal_line(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _wal_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.wal")


def _parse_wal_metadata(wal: Path) -> tuple[int, int, str] | None:
    if not os.path.lexists(wal):
        return None
    if wal.is_symlink():
        raise contract_error("refusing to use a symlinked WAL file", INVALID_RECORD)
    try:
        meta = json.loads(wal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return None
    if (
        isinstance(meta, dict)
        and isinstance(meta.get("prior_size"), int)
        and not isinstance(meta.get("prior_size"), bool)
        and meta["prior_size"] >= 0
        and isinstance(meta.get("payload_len"), int)
        and not isinstance(meta.get("payload_len"), bool)
        and meta["payload_len"] > 0
        and isinstance(meta.get("sha256"), str)
    ):
        return meta["prior_size"], meta["payload_len"], meta["sha256"]
    return None


def _open_nofollow(path: Path, flags: int, mode: int = 0o600) -> int:
    if path.is_symlink():
        raise contract_error("refusing to open a symlinked store file", INVALID_RECORD)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    return os.open(path, flags, mode)


def _recover_wal(
    path: Path,
    *,
    mapped_os_errors: Callable[[], AbstractContextManager[None]],
    fsync_dir: Callable[[Path], None],
) -> None:
    """Reconcile any leftover append WAL from a prior crashed writer (caller holds project lock)."""
    with mapped_os_errors():
        wal = _wal_path(path)
        if not os.path.lexists(wal):
            return
        meta = _parse_wal_metadata(wal)
        if meta is not None and path.exists():
            prior_size, payload_len, expected_sha = meta
            fd = _open_nofollow(path, os.O_RDWR)
            try:
                cur_size = os.fstat(fd).st_size
                if cur_size == prior_size + payload_len:
                    os.lseek(fd, prior_size, os.SEEK_SET)
                    tail = os.read(fd, payload_len)
                    if len(tail) != payload_len or hashlib.sha256(tail).hexdigest() != expected_sha:
                        os.ftruncate(fd, prior_size)
                        os.fsync(fd)
                elif cur_size > prior_size:
                    os.ftruncate(fd, prior_size)
                    os.fsync(fd)
            finally:
                os.close(fd)
        if os.path.lexists(wal) and not wal.is_symlink():
            wal.unlink()
            fsync_dir(path.parent)


def _effective_read_limit(path: Path) -> int | None:
    """Return a safe byte prefix limit for lock-free reads if an uncommitted WAL is present."""
    wal = _wal_path(path)
    meta = _parse_wal_metadata(wal)
    if meta is None or not path.exists():
        return None
    prior_size, payload_len, expected_sha = meta
    try:
        cur_size = path.stat().st_size
        if cur_size <= prior_size:
            return None
        if cur_size == prior_size + payload_len:
            with path.open("rb") as fh:
                fh.seek(prior_size)
                tail = fh.read(payload_len)
            if len(tail) == payload_len and hashlib.sha256(tail).hexdigest() == expected_sha:
                return None
        return prior_size
    except OSError:
        return None


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    written = 0
    while written < len(view):
        n = os.write(fd, view[written:])
        if n <= 0:
            raise OSError(errno.EIO, "short write")
        written += n


def _append_with_wal(
    path: Path,
    line: str,
    *,
    mapped_os_errors: Callable[[], AbstractContextManager[None]],
    fsync_dir: Callable[[Path], None],
) -> None:
    """O(1) crash-safe append via a tiny per-record WAL and ftruncate rollback."""
    with mapped_os_errors():
        payload = (line + "\n").encode("utf-8")
        wal = _wal_path(path)
        if os.path.lexists(wal) and wal.is_symlink():
            raise contract_error("refusing to use a symlinked WAL file", INVALID_RECORD)
        fd = _open_nofollow(path, os.O_RDWR)
        wal_tmp: Path | None = None
        wal_installed = False
        appended = False
        try:
            prior_size = os.fstat(fd).st_size
            wal_body = _canonical_wal_line(
                {
                    "prior_size": prior_size,
                    "payload_len": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
            wfd, wtmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.wal.", suffix=".tmp")
            wal_tmp = Path(wtmp_name)
            with os.fdopen(wfd, "w", encoding="utf-8") as handle:
                handle.write(wal_body + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(wal_tmp, wal)
            wal_tmp = None
            wal_installed = True
            fsync_dir(path.parent)

            os.lseek(fd, prior_size, os.SEEK_SET)
            _write_all(fd, payload)
            appended = True
            os.fsync(fd)

            wal.unlink()
            wal_installed = False
            fsync_dir(path.parent)
        except BaseException:
            if appended:
                with contextlib.suppress(OSError):
                    os.ftruncate(fd, prior_size)
                    os.fsync(fd)
            if wal_installed and os.path.lexists(wal) and not wal.is_symlink():
                with contextlib.suppress(OSError):
                    wal.unlink()
                    fsync_dir(path.parent)
            raise
        finally:
            os.close(fd)
            if wal_tmp is not None and os.path.lexists(wal_tmp) and not wal_tmp.is_symlink():
                with contextlib.suppress(OSError):
                    wal_tmp.unlink()
