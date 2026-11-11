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
import json
import os

_LEDGER_NAME = "outputs.jsonl"
# Past this size the ledger is compacted down to entries that still match a file.
_COMPACT_BYTES = 1024 * 1024
# Windows has no O_NOFOLLOW; there the realpath() resolution is the guard.
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _state_dir() -> str:
    explicit = os.environ.get("KINOCUT_STATE_DIR")
    if explicit:
        return os.path.expanduser(explicit)
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return os.path.join(base, "kinocut")


def _ledger_path() -> str:
    return os.path.join(_state_dir(), _LEDGER_NAME)


def _identity(st: os.stat_result) -> list[int]:
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def _open_ledger(flags: int) -> int:
    directory = _state_dir()
    os.makedirs(directory, mode=0o700, exist_ok=True)
    return os.open(_ledger_path(), flags | _NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o600)


def record_output(path: str) -> None:
    """Remember that Kinocut wrote ``path`` with its current identity."""
    with contextlib.suppress(OSError, ValueError):
        resolved = os.path.realpath(path)
        current = os.stat(resolved, follow_symlinks=False)
        line = json.dumps({"path": resolved, "id": _identity(current)}, separators=(",", ":")) + "\n"
        fd = _open_ledger(os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        try:
            os.write(fd, line.encode("utf-8"))
            size = os.fstat(fd).st_size
        finally:
            os.close(fd)
        if size > _COMPACT_BYTES:
            _compact()


def _entries() -> list[tuple[str, list[int]]]:
    try:
        fd = _open_ledger(os.O_RDONLY)
    except OSError:
        return []
    with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as stream:
        rows = []
        for raw in stream:
            with contextlib.suppress(ValueError, TypeError, KeyError):
                row = json.loads(raw)
                rows.append((str(row["path"]), [int(v) for v in row["id"]]))
        return rows


def owns(path: str) -> bool:
    """True when ``path`` is, right now, a file Kinocut recorded writing."""
    resolved = os.path.realpath(path)
    try:
        current = _identity(os.stat(resolved, follow_symlinks=False))
    except OSError:
        return False
    return any(p == resolved and ident == current for p, ident in _entries())


def _compact() -> None:
    keep: dict[str, list[int]] = {}
    for p, ident in _entries():
        with contextlib.suppress(OSError):
            if _identity(os.stat(p, follow_symlinks=False)) == ident:
                keep[p] = ident
    staged = _ledger_path() + f".{os.getpid()}.tmp"
    with contextlib.suppress(OSError):
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for p, ident in keep.items():
                stream.write(json.dumps({"path": p, "id": ident}, separators=(",", ":")) + "\n")
        # A record appended during compaction can be lost; that file then just
        # cannot be cleaned up by Kinocut, which is the safe direction.
        os.replace(staged, _ledger_path())
