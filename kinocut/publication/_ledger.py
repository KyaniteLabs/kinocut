"""A durable record of the files Kinocut wrote, so cleanup can prove ownership.

A filename such as ``clip_trimmed.mp4`` says nothing about who made the file.
Every output Kinocut writes is recorded here with its file identity (device,
inode, size, modification time). ``video_cleanup`` deletes a file only when
its current identity matches a recorded one, so a user's own file with a
Kinocut-looking name, or a new file that later took over the same path, is
never treated as Kinocut's.

Recording is best effort: if the ledger cannot be written, the output still
succeeds and cleanup simply refuses to delete that file later (fail closed).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import threading
from collections.abc import Iterator

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None

_LEDGER_NAME = "outputs.jsonl"
# Past this size the ledger is compacted down to entries that still match a file.
_COMPACT_BYTES = 1024 * 1024
# Windows has no O_NOFOLLOW; there the realpath() resolution is the guard.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_Snapshot = frozenset[tuple[str, tuple[int, ...]]]
_cached: tuple[bytes, _Snapshot] | None = None
_THREAD_LOCK = threading.Lock()


@contextlib.contextmanager
def _ledger_lock() -> Iterator[None]:
    """Serialize ledger appends and compactions across threads and POSIX processes."""
    with _THREAD_LOCK:
        if _fcntl is None:
            yield
            return
        directory = state_dir()
        os.makedirs(directory, mode=0o700, exist_ok=True)
        lock_path = os.path.join(directory, f".{_LEDGER_NAME}.lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
        try:
            _fcntl.flock(fd, _fcntl.LOCK_EX)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    _fcntl.flock(fd, _fcntl.LOCK_UN)
        finally:
            os.close(fd)


def state_dir() -> str:
    explicit = os.environ.get("KINOCUT_STATE_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "kinocut")


def _ledger_path() -> str:
    return os.path.join(state_dir(), _LEDGER_NAME)


def _identity(st: os.stat_result) -> list[int]:
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def _open_ledger(flags: int) -> int:
    directory = state_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    return os.open(_ledger_path(), flags | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)


def record_output(path: str) -> None:
    """Remember that Kinocut wrote ``path`` with its current identity."""
    with contextlib.suppress(OSError, ValueError):
        resolved = os.path.realpath(path)
        current = os.stat(resolved, follow_symlinks=False)
        _record_identity(resolved, current)


def _record_identity(resolved: str, current: os.stat_result) -> None:
    global _cached
    with contextlib.suppress(OSError, ValueError), _ledger_lock():
        line = json.dumps({"path": resolved, "id": _identity(current)}, separators=(",", ":")) + "\n"
        fd = _open_ledger(os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            size = os.fstat(fd).st_size
        finally:
            os.close(fd)
        _cached = None
        if size > _COMPACT_BYTES:
            _compact_unlocked()


def _entries() -> _Snapshot:
    global _cached
    try:
        fd = _open_ledger(os.O_RDONLY)
    except OSError:
        return frozenset()
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read()
    digest = hashlib.blake2b(raw, digest_size=16).digest()
    cached = _cached
    if cached is not None and cached[0] == digest:
        return cached[1]
    rows = set()
    for line in raw.decode("utf-8", errors="replace").split("\n"):
        if not line:
            continue
        with contextlib.suppress(ValueError, TypeError, KeyError):
            row = json.loads(line)
            rows.add((str(row["path"]), tuple(int(v) for v in row["id"])))
    snapshot = frozenset(rows)
    _cached = digest, snapshot
    return snapshot


def owns(path: str) -> bool:
    """True when ``path`` is, right now, a file Kinocut recorded writing."""
    resolved = os.path.realpath(path)
    try:
        current = _identity(os.stat(resolved, follow_symlinks=False))
    except OSError:
        return False
    return (resolved, tuple(current)) in _entries()


def _compact_unlocked() -> None:
    global _cached
    keep: dict[str, tuple[int, ...]] = {}
    for p, ident in _entries():
        with contextlib.suppress(OSError):
            if tuple(_identity(os.stat(p, follow_symlinks=False))) == ident:
                keep[p] = ident
    staged = _ledger_path() + f".{os.getpid()}.{secrets.token_hex(8)}.tmp"
    replaced = False
    try:
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for p, ident in keep.items():
                stream.write(json.dumps({"path": p, "id": ident}, separators=(",", ":")) + "\n")
            stream.flush()
            with contextlib.suppress(OSError):
                os.fsync(stream.fileno())
        os.replace(staged, _ledger_path())
        replaced = True
        _cached = None
    except OSError:
        return
    finally:
        if not replaced:
            with contextlib.suppress(OSError):
                os.unlink(staged)


def _compact() -> None:
    with contextlib.suppress(OSError), _ledger_lock():
        _compact_unlocked()
