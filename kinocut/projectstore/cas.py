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

    manifest = _manifest(project, digest)
    if manifest is None:
        raise contract_error("CAS digest is not recorded in this project", INVALID_RECORD)
    target, actual, size = store.safe_target(project, manifest.blob_location), hashlib.sha256(), 0
    try:
        with target.open("rb") as reader:
            while chunk := reader.read(_CHUNK):
                actual.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise contract_error("CAS blob is unavailable", INVALID_RECORD) from exc
    if "sha256:" + actual.hexdigest() != digest or size != manifest.byte_size:
        raise contract_error("CAS blob failed its manifest integrity check", INVALID_RECORD)
    return target


__all__ = ["ingest_blob", "resolve_blob"]
