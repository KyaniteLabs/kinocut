"""Byte-hash-first idempotent asset ingest (Plan 00 Task 3).

Ingest hashes the *source bytes before anything else*, streaming the file so a
large video is never read whole into memory. A re-ingest of identical bytes
short-circuits to the existing :class:`AssetRecord` and never duplicates the
stored file. The digest check, the content-addressed copy, and the record
append all run inside a **single** project-lock transaction, so two concurrent
ingests of the same asset collapse to exactly one record. The produced record
carries a project-relative ``original_location`` only, and any filesystem error
surfaces as a stable, privacy-safe :class:`MCPVideoError`.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
from pathlib import Path

from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.asset import (
    AssetRecord,
    GenerationLineage,
    MediaKind,
    UsageRightsStatus,
)
from kinocut.projectstore import layout, store

# Extension → media kind. Unknown extensions default to video (the primary
# medium); the mapping stays small and explicit rather than guessing by probing.
_EXT_TO_KIND: dict[str, MediaKind] = {
    ".mp4": MediaKind.VIDEO,
    ".mov": MediaKind.VIDEO,
    ".mkv": MediaKind.VIDEO,
    ".webm": MediaKind.VIDEO,
    ".avi": MediaKind.VIDEO,
    ".m4v": MediaKind.VIDEO,
    ".mp3": MediaKind.AUDIO,
    ".wav": MediaKind.AUDIO,
    ".aac": MediaKind.AUDIO,
    ".m4a": MediaKind.AUDIO,
    ".flac": MediaKind.AUDIO,
    ".ogg": MediaKind.AUDIO,
    ".png": MediaKind.IMAGE,
    ".jpg": MediaKind.IMAGE,
    ".jpeg": MediaKind.IMAGE,
    ".gif": MediaKind.IMAGE,
    ".webp": MediaKind.IMAGE,
    ".bmp": MediaKind.IMAGE,
    ".tiff": MediaKind.IMAGE,
    ".srt": MediaKind.SUBTITLE,
    ".vtt": MediaKind.SUBTITLE,
    ".ass": MediaKind.SUBTITLE,
    ".ssa": MediaKind.SUBTITLE,
}

_CHUNK = 1 << 20  # 1 MiB streaming chunk


def _infer_media_kind(name: str) -> MediaKind:
    """Map a filename extension to a closed media kind, defaulting to video."""

    return _EXT_TO_KIND.get(Path(name).suffix.lower(), MediaKind.VIDEO)


def _best_effort_unlink(path: Path) -> None:
    """Remove a temp file, swallowing any OS error so cleanup never masks it."""

    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _find_active_leaf(project: store.Project, asset_id: str) -> AssetRecord | None:
    """Return the unique *active* (non-superseded) asset record for ``asset_id``.

    Idempotence and enrichment must reconcile against the active leaf — the
    record for these bytes that no later record supersedes — not the first
    record on file, which after an enrichment is the superseded original. The
    superseded target ids are collected across every asset record, then the
    records matching ``asset_id`` whose own id is not among them are the active
    leaves: zero means the bytes are new, exactly one is the leaf to
    return/compare, and two or more is an ambiguous state that fails closed with
    a stable, privacy-safe contract error.
    """

    records = [record for record in store.read_records(project, "asset_record") if isinstance(record, AssetRecord)]
    superseded = {record.supersedes for record in records if record.supersedes is not None}
    matching = [record for record in records if record.asset_id == asset_id and record.record_id not in superseded]
    if len(matching) > 1:
        raise contract_error("asset has multiple active records; cannot reconcile ingest", INVALID_RECORD)
    return matching[0] if matching else None


def _hash_copy_to_temp(project: store.Project, src: Path) -> tuple[str, int, Path]:
    """In one pass, stream ``src`` into a secure store temp file while hashing.

    The source is opened ``O_NOFOLLOW`` (a symlinked source is refused) and the
    bytes are hashed *and* written in the same read, so a concurrent mutation of
    the source cannot make the stored bytes disagree with the recorded digest.
    Returns the ``sha256`` id, the byte size, and the temp path (same filesystem
    as the final destination, ready for an atomic install).
    """

    assets_root = store.safe_target(project, layout.assets_dir())
    with store._mapped_os_errors():
        assets_root.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=assets_root, prefix=".ingest.", suffix=".tmp")
    tmp = Path(tmp_name)
    digest = hashlib.sha256()
    size = 0
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        src_fd = os.open(src, flags)
        with os.fdopen(src_fd, "rb") as reader, os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(_CHUNK):
                digest.update(chunk)
                size += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
    except (OSError, UnicodeError) as exc:
        _best_effort_unlink(tmp)
        raise contract_error("could not read the ingest source", INVALID_RECORD) from exc
    return "sha256:" + digest.hexdigest(), size, tmp


def _install(tmp: Path, dest: Path) -> None:
    """Atomically move the hashed temp file to its content-addressed destination."""

    with store._mapped_os_errors():
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp, dest)
        store._fsync_dir(dest.parent)


def _asset_payload(
    project: store.Project,
    *,
    asset_id: str,
    byte_size: int,
    original_location: str,
    media_kind: MediaKind,
    lineage: GenerationLineage | None,
    usage_rights_status: UsageRightsStatus,
    usage_rights_evidence_ref: str | None,
) -> dict[str, Any]:
    """Build the ``AssetRecord`` payload validated at the store boundary."""

    payload: dict[str, Any] = {
        "project_id": project.project_id,
        "created_by": "tool",
        "asset_id": asset_id,
        "media_kind": media_kind,
        "original_location": original_location,
        "byte_size": byte_size,
        "usage_rights_status": usage_rights_status,
    }
    if lineage is not None:
        # Never ``.model_dump()`` an unvalidated lineage — a raw dict or arbitrary
        # object has no such method and would raise a bare ``AttributeError``.
        # Hand the raw value to ``validate_record`` so the store boundary owns the
        # privacy-safe error mapping (and revalidates model instances).
        payload["lineage"] = lineage
    if usage_rights_evidence_ref is not None:
        payload["usage_rights_evidence_ref"] = usage_rights_evidence_ref
    return payload


def _has_no_metadata(record: AssetRecord) -> bool:
    """True when a record carries no lineage and the default *unverified* rights."""

    return (
        record.lineage is None
        and record.usage_rights_status is UsageRightsStatus.UNKNOWN
        and record.usage_rights_evidence_ref is None
    )


def _same_metadata(existing: AssetRecord, candidate: AssetRecord) -> bool:
    """True when both records agree on lineage and the full rights posture."""

    return (
        existing.lineage == candidate.lineage
        and existing.usage_rights_status is candidate.usage_rights_status
        and existing.usage_rights_evidence_ref == candidate.usage_rights_evidence_ref
    )


def _reconcile(project: store.Project, existing: AssetRecord, candidate: AssetRecord) -> AssetRecord:
    """Reconcile a duplicate-byte ingest with the record already on file.

    A request that supplies no metadata, or metadata identical to the stored
    record, is idempotent and returns the existing record. A *plain* prior asset
    (no lineage, default unverified rights) is enriched by an append-only record
    that supersedes it and carries the new metadata against the same stored
    bytes. Any other divergence is a conflicting re-ingest and is rejected.
    """

    if _has_no_metadata(candidate) or _same_metadata(existing, candidate):
        return existing
    if _has_no_metadata(existing):
        enriched = existing.model_copy(
            update={
                "record_id": None,
                "supersedes": existing.record_id,
                "lineage": candidate.lineage,
                "usage_rights_status": candidate.usage_rights_status,
                "usage_rights_evidence_ref": candidate.usage_rights_evidence_ref,
            }
        )
        return store.append_record_locked(project, enriched)
    raise contract_error("ingest metadata conflicts with the recorded original", INVALID_RECORD)


def ingest_asset(
    project: store.Project,
    source_path: str | Path,
    *,
    lineage: GenerationLineage | None = None,
    usage_rights_status: UsageRightsStatus = UsageRightsStatus.UNKNOWN,
    usage_rights_evidence_ref: str | None = None,
) -> AssetRecord:
    """Ingest ``source_path`` into the project store, idempotently by byte digest.

    The whole operation — single-pass hash+copy into a secure temp, digest
    existence check, content-addressed install, and record append — runs under
    one project lock, so concurrent identical ingests produce a single
    :class:`AssetRecord` and a source mutation can never split digest from bytes.

    Optional generation ``lineage`` and a rights posture are validated *before*
    the duplicate check, so malformed metadata is rejected even for a re-ingest
    of already-stored bytes. On a duplicate, a plain prior asset is enriched by an
    append-only superseding record; identical metadata is idempotent; conflicting
    metadata raises a privacy-safe :class:`~kinocut.errors.MCPVideoError`.
    """

    src = Path(source_path)
    with store._project_lock(project):
        asset_id, byte_size, tmp = _hash_copy_to_temp(project, src)
        try:
            rel = layout.asset_relative_path(asset_id, src.name)
            candidate = validate_record(
                AssetRecord,
                _asset_payload(
                    project,
                    asset_id=asset_id,
                    byte_size=byte_size,
                    original_location=str(rel),
                    media_kind=_infer_media_kind(src.name),
                    lineage=lineage,
                    usage_rights_status=usage_rights_status,
                    usage_rights_evidence_ref=usage_rights_evidence_ref,
                ),
            )
            existing = _find_active_leaf(project, asset_id)
            if existing is not None:
                return _reconcile(project, existing, candidate)
            _install(tmp, store.safe_target(project, rel))
            return store.append_record_locked(project, candidate)
        finally:
            _best_effort_unlink(tmp)
