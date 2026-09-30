"""Causal CAS availability shared by ingestion, resolution and collection.

Record kinds have independent append order, so availability uses explicit GC
receipt references and per-digest supersession, never timestamps. A durable
restoring intent makes an interrupted byte installation fail closed on reopen.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import CASBlobLifecycleRecord, CASGCReceiptRecord, CASManifestRecord
from kinocut.projectstore import store
from kinocut.projectstore.ingest import _best_effort_unlink


def availability(
    project: store.Project,
) -> tuple[dict[str, CASGCReceiptRecord], dict[str, CASBlobLifecycleRecord]]:
    """Return latest GC receipts and validated per-digest lifecycle heads."""
    receipts = store.read_records(project, "cas_gc")
    receipt_by_id = {r.record_id: r for r in receipts}
    latest_gc = {digest: r for r in receipts for digest in r.deleted_digests}
    heads: dict[str, CASBlobLifecycleRecord] = {}
    records = store.read_records(project, "cas_blob_lifecycle")
    if not records:
        return latest_gc, heads
    manifest_records = store.read_records(project, "cas_manifest")
    manifests = {r.digest: r for r in manifest_records}
    if len(manifests) != len(manifest_records):
        raise contract_error("CAS digest has multiple manifest records", INVALID_RECORD)
    backup_owners: dict[str, str] = {}
    for record in records:
        manifest, previous = manifests.get(record.digest), heads.get(record.digest)
        if manifest is None or record.manifest_record_id != manifest.record_id:
            raise contract_error("CAS lifecycle references an invalid manifest", INVALID_RECORD)
        if record.supersedes != (previous.record_id if previous else None):
            raise contract_error("CAS lifecycle does not form one per-digest chain", INVALID_RECORD)
        if record.backup_location is not None:
            owner = backup_owners.setdefault(record.backup_location, record.digest)
            if owner != record.digest:
                raise contract_error("CAS repair backup belongs to multiple digests", INVALID_RECORD)
        if record.after_gc_receipt_id is not None:
            receipt = receipt_by_id.get(record.after_gc_receipt_id)
            if receipt is None or record.digest not in receipt.deleted_digests:
                raise contract_error("CAS lifecycle references an invalid GC receipt", INVALID_RECORD)
        if record.state == "available" and (
            previous is None
            or previous.state != "restoring"
            or record.after_gc_receipt_id != previous.after_gc_receipt_id
            or record.backup_location != previous.backup_location
        ):
            raise contract_error("CAS completion requires a matching repair intent", INVALID_RECORD)
        heads[record.digest] = record
    return latest_gc, heads


def unavailable_digests(project: store.Project) -> set[str]:
    """A new deletion invalidates earlier restoration; pending repairs block reads."""
    latest_gc, heads = availability(project)
    unavailable = set(latest_gc)
    for digest, head in heads.items():
        receipt = latest_gc.get(digest)
        if head.state == "available" and head.after_gc_receipt_id == (receipt.record_id if receipt else None):
            unavailable.discard(digest)
        else:
            unavailable.add(digest)
    return unavailable


def _append_state(project, manifest, state, previous, gc_receipt, backup_location):
    record = validate_record(
        CASBlobLifecycleRecord,
        {
            "project_id": project.project_id,
            "created_by": "tool",
            "digest": manifest.digest,
            "manifest_record_id": manifest.record_id,
            "state": state,
            "supersedes": previous.record_id if previous else None,
            "after_gc_receipt_id": gc_receipt.record_id if gc_receipt else None,
            "backup_location": backup_location,
        },
    )
    return store.append_record_locked(project, record)


def restore_blob(project: store.Project, manifest: CASManifestRecord, temporary: Path) -> None:
    """Called under the project lock; commit bytes only with a recorded completion."""
    latest_gc, heads = availability(project)
    receipt = latest_gc.get(manifest.digest)
    target = store.safe_target(project, manifest.blob_location)
    if target.exists() and not target.is_file():
        raise contract_error("CAS repair refuses a non-regular blob target", INVALID_RECORD)
    backup_location = (
        (target.relative_to(project.root).parent / f".cas-repair.{secrets.token_hex(16)}").as_posix()
        if target.exists()
        else None
    )
    intent = _append_state(project, manifest, "restoring", heads.get(manifest.digest), receipt, backup_location)
    backup_path = store.safe_target(project, backup_location) if backup_location else None
    backup = _stash_previous(target, backup_path)
    try:
        with store._mapped_os_errors():
            target = store.safe_target(project, manifest.blob_location)
            os.replace(temporary, target)
            store._fsync_dir(target.parent)
        _append_state(project, manifest, "available", intent, receipt, backup_location)
    except BaseException:
        _restore_previous(target, backup)
        raise
    else:
        cleanup_backups(project, manifest.digest)


def _stash_previous(target: Path, backup: Path | None) -> Path | None:
    with store._mapped_os_errors():
        if backup is None:
            return None
        fd = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            os.replace(target, backup)
            store._fsync_dir(target.parent)
        except BaseException:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            else:
                _best_effort_unlink(backup)
            raise
        return backup


def _restore_previous(target: Path, backup: Path | None) -> None:
    with store._mapped_os_errors():
        if backup is None:
            target.unlink(missing_ok=True)
        else:
            os.replace(backup, target)
        store._fsync_dir(target.parent)


def cleanup_backups(project: store.Project, digest: str) -> None:
    """Remove only explicitly recorded repair-owned files, never directory scans."""
    for record in store.read_records(project, "cas_blob_lifecycle"):
        if record.digest == digest and record.backup_location is not None:
            with store._mapped_os_errors():
                backup = store.safe_target(project, record.backup_location)
                backup.unlink(missing_ok=True)
                store._fsync_dir(backup.parent)


def owned_blob_bytes(project: store.Project, manifests: list[CASManifestRecord]) -> dict[str, int]:
    """Observed bytes of canonical blobs and explicitly recorded repair backups."""
    locations = {m.digest: {m.blob_location} for m in manifests}
    for record in store.read_records(project, "cas_blob_lifecycle"):
        if record.digest in locations and record.backup_location is not None:
            locations[record.digest].add(record.backup_location)
    sizes = {}
    with store._mapped_os_errors():
        for digest, owned in locations.items():
            total = 0
            for location in owned:
                target = store.safe_target(project, location)
                if target.is_file():
                    total += target.stat().st_size
            sizes[digest] = total
    return sizes
