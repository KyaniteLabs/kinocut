"""Immutable content-addressed blob ingest and resolution."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import cast

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import CASManifestRecord
from kinocut.projectstore import layout, store
from kinocut.projectstore.cas_lifecycle import cleanup_backups, restore_blob, unavailable_digests
from kinocut.projectstore.ingest import _best_effort_unlink, _hash_copy_to_temp

_CHUNK = 1 << 20


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


def resolve_blob(project: store.Project, digest: str) -> Path:
    """Resolve and integrity-check a recorded blob after any project reopen."""

    with store._project_lock(project):
        manifest = _manifest(project, digest)
        if manifest is None:
            raise contract_error("CAS digest is not recorded in this project", INVALID_RECORD)
        if digest in _deleted_digests(project):
            raise contract_error(
                "CAS blob is unavailable after garbage collection or interrupted restoration", INVALID_RECORD
            )
        target = store.safe_target(project, manifest.blob_location)
        if not _blob_matches(target, manifest):
            raise contract_error("CAS blob is unavailable or failed its manifest integrity check", INVALID_RECORD)
        return target


def _blob_matches(target: Path, manifest: CASManifestRecord) -> bool:
    actual, size = hashlib.sha256(), 0
    try:
        if not target.is_file():
            return False
        fd = os.open(target, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as reader:
            if os.fstat(reader.fileno()).st_size != manifest.byte_size:
                return False
            while chunk := reader.read(_CHUNK):
                actual.update(chunk)
                size += len(chunk)
    except OSError:
        return False
    return "sha256:" + actual.hexdigest() == manifest.digest and size == manifest.byte_size


def _deleted_digests(project: store.Project) -> set[str]:
    """Return unavailable digests, honoring recorded restoration generations."""
    return unavailable_digests(project)


__all__ = ["ingest_blob", "resolve_blob"]
