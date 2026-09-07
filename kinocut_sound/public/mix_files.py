"""Descriptor-relative reads and exclusive publication for local mix assets."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import stat
import uuid

from kinocut_sound.limits import MAX_MIX_INPUT_BYTES, MAX_MIX_REQUEST_BYTES
from kinocut_sound.mix._errors import MIX_INPUT_INVALID, MIX_OVER_LIMIT, MIX_UNSAFE_PATH, mix_error
from kinocut_sound.public.mix_request import relative_path


def require_safe_filesystem() -> None:
    if not (
        hasattr(os, "O_NOFOLLOW")
        and hasattr(os, "O_DIRECTORY")
        and all(fn in os.supports_dir_fd for fn in (os.open, os.link, os.unlink))
        and os.link in os.supports_follow_symlinks
    ):
        raise mix_error("descriptor-relative mix filesystem operations unavailable", "mix_platform_unavailable")


@contextmanager
def open_root(root: str):
    require_safe_filesystem()
    fd = -1
    try:
        fd = os.open(Path(root).resolve(strict=True), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        yield fd
    except OSError as exc:
        raise mix_error("mix project directory cannot be accessed", MIX_UNSAFE_PATH) from exc
    finally:
        if fd >= 0:
            os.close(fd)


@contextmanager
def open_parent(root_fd: int, path: str):
    parts = relative_path(path).split("/")
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd, parts[-1]
    except OSError as exc:
        raise mix_error("mix asset parent is missing or unsafe", MIX_UNSAFE_PATH) from exc
    finally:
        os.close(fd)


def _read_regular_file(root_fd: int, path: str, remaining: int) -> bytes:
    with open_parent(root_fd, path) as (parent, name):
        try:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except OSError as exc:
            raise mix_error("mix asset cannot be opened safely", MIX_UNSAFE_PATH) from exc
        with os.fdopen(fd, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise mix_error("mix asset must be a regular file", MIX_UNSAFE_PATH)
            if before.st_size > min(remaining, MAX_MIX_INPUT_BYTES):
                raise mix_error("mix asset exceeds byte limit", MIX_OVER_LIMIT)
            data = handle.read(min(remaining, MAX_MIX_INPUT_BYTES) + 1)
            after = os.fstat(handle.fileno())
    markers = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if len(data) > remaining or any(getattr(before, k) != getattr(after, k) for k in markers):
        raise mix_error("mix asset changed during read", MIX_INPUT_INVALID)
    return data


def read_asset(root_fd: int, path: str, expected_hash: str, remaining: int) -> bytes:
    data = _read_regular_file(root_fd, path, remaining)
    if "sha256:" + hashlib.sha256(data).hexdigest() != expected_hash:
        raise mix_error("mix asset hash mismatch", MIX_INPUT_INVALID)
    return data


@contextmanager
def staged_output(parent_fd: int):
    name = ".kinocut-mix-" + uuid.uuid4().hex
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent_fd)
    try:
        yield fd, name
    finally:
        os.close(fd)
        os.unlink(name, dir_fd=parent_fd)


def publish(parent_fd: int, stage: str, destination: str) -> None:
    try:
        os.link(stage, destination, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
    except FileExistsError as exc:
        raise mix_error("mix output already exists; choose a new output path", "mix_output_conflict") from exc
    except OSError as exc:
        raise mix_error("exclusive mix publication unavailable", "mix_publish_failed") from exc


def load_request_file(path: str) -> str:
    """Read a caller-selected CLI request file with a strict byte ceiling."""
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_MIX_REQUEST_BYTES:
                raise mix_error("mix request file is not a bounded regular file", MIX_OVER_LIMIT)
            raw = handle.read(MAX_MIX_REQUEST_BYTES + 1)
        if len(raw) > MAX_MIX_REQUEST_BYTES:
            raise mix_error("mix request file exceeds byte limit", MIX_OVER_LIMIT)
        return raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise mix_error("mix request file cannot be read", MIX_INPUT_INVALID) from exc
