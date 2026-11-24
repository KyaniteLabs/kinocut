"""Immutable content-addressed blob ingest and resolution."""

from __future__ import annotations

import hashlib
import os
from threading import Lock
from pathlib import Path
from typing import cast

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import CASManifestRecord
from kinocut.projectstore import layout, store
from kinocut.projectstore.cas_lifecycle import cleanup_backups, restore_blob, unavailable_digests
from kinocut.projectstore.ingest import _best_effort_unlink, _hash_copy_to_temp

_CHUNK = 1 << 20
_TRUSTED_LINUX_FSTYPES = frozenset({"ext2", "ext3", "ext4", "xfs", "btrfs", "tmpfs", "zfs"})
_VERIFIED: dict[tuple[int, ...], str] = {}
_CACHE_LOCK = Lock()


def _identity(info: os.stat_result) -> tuple[int, ...]:
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def _device_has_trusted_ctime(dev: int) -> bool:
    """Return True only when the device is confirmed as a local POSIX filesystem with reliable ctime."""
    if os.name != "posix" or not hasattr(os, "major") or not hasattr(os, "minor"):
        return False
    dev_id = f"{os.major(dev)}:{os.minor(dev)}"
    try:
        with open("/proc/self/mountinfo", encoding="utf-8") as handle:
            for line in handle:
                parts = line.split(" - ", 1)
                if len(parts) != 2:
                    continue
                head = parts[0].split()
                tail = parts[1].split()
                if len(head) >= 3 and head[2] == dev_id and tail:
                    return tail[0] in _TRUSTED_LINUX_FSTYPES
    except OSError:
        return False
    return False


def _cacheable_identity(info: os.stat_result) -> tuple[int, ...] | None:
    """Return a cache key only when the backing filesystem reliably advances ctime on rewrites."""
    if info.st_ino == 0 or info.st_ctime_ns <= 0 or not _device_has_trusted_ctime(info.st_dev):
        return None
    return _identity(info)


def _manifest(project: store.Project, digest: str) -> CASManifestRecord | None:
    matches = [
        r
        for r in store.read_records(project, "cas_manifest")
        if isinstance(r, CASManifestRecord) and r.digest == digest
    ]
    if len(matches) > 1:
        raise contract_error("CAS digest has multiple manifest records", INVALID_RECORD)
    return matches[0] if matches else None


def ingest_blob(project: store.Project, source_path: str | Path, *, media_type: str | None = None) -> CASManifestRecord:
    """Hash and atomically install one immutable blob, idempotently by digest."""

    with store._project_lock(project):
        digest, byte_size, temporary = _hash_copy_to_temp(project, Path(source_path))
        try:
            if existing := _manifest(project, digest):
                if byte_size != existing.byte_size:
                    raise contract_error("CAS manifest byte size disagrees with its source digest", INVALID_RECORD)
                target = store.safe_target(project, existing.blob_location)
                if digest in unavailable_digests(project) or not _blob_matches(target, existing):
                    restore_blob(project, existing, temporary)
                else:
                    cleanup_backups(project, digest)
                return existing
            relative = layout.blob_relative_path(digest)
            target = store.safe_target(project, relative)
            record = validate_record(
                CASManifestRecord,
                {
                    "project_id": project.project_id,
                    "created_by": "tool",
                    "digest": digest,
                    "byte_size": byte_size,
                    "blob_location": str(relative),
                    "media_type": media_type,
                },
            )
            try:
                with store._mapped_os_errors():
                    os.replace(temporary, target)
                    store._fsync_dir(target.parent)
                return cast(CASManifestRecord, store.append_record_locked(project, record))
            except BaseException:
                _best_effort_unlink(target)
                raise
        finally:
            _best_effort_unlink(temporary)


def resolve_blob(project: store.Project, digest: str, *, verify_content: bool = True) -> Path:
    """Resolve and integrity-check a recorded blob; set verify_content=False to opt into cached reuse."""

    with store._project_lock(project):
        manifest = _manifest(project, digest)
        if manifest is None:
            raise contract_error("CAS digest is not recorded in this project", INVALID_RECORD)
        if digest in _deleted_digests(project):
            raise contract_error(
                "CAS blob is unavailable after garbage collection or interrupted restoration", INVALID_RECORD
            )
        target = store.safe_target(project, manifest.blob_location)
        if not _blob_matches(target, manifest, verify_content=verify_content):
            raise contract_error("CAS blob is unavailable or failed its manifest integrity check", INVALID_RECORD)
        return target


def _blob_matches(target: Path, manifest: CASManifestRecord, *, verify_content: bool = True) -> bool:
    try:
        if not target.is_file():
            return False
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as reader:
            before = os.fstat(fd)
            if before.st_size != manifest.byte_size:
                return False
            key = _identity(before)
            cache_key = _cacheable_identity(before)
            if not verify_content and cache_key is not None:
                with _CACHE_LOCK:
                    if cache_key in _VERIFIED:
                        return _VERIFIED[cache_key] == manifest.digest
            actual = hashlib.sha256()
            while chunk := reader.read(_CHUNK):
                actual.update(chunk)
            if key != _identity(os.fstat(fd)):
                return False
            digest = "sha256:" + actual.hexdigest()
            if cache_key is not None:
                with _CACHE_LOCK:
                    if len(_VERIFIED) >= 1024:
                        _VERIFIED.pop(next(iter(_VERIFIED)))
                    _VERIFIED[cache_key] = digest
            return digest == manifest.digest
    except OSError:
        return False


def _deleted_digests(project: store.Project) -> set[str]:
    """Return unavailable digests, honoring recorded restoration generations."""
    return unavailable_digests(project)


__all__ = ["ingest_blob", "resolve_blob"]
