"""Bounded CAS reachability accounting and garbage collection."""

from __future__ import annotations

from typing import cast

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import (
    CASGCReceiptRecord,
    CASManifestRecord,
    EditProjectRecord,
    EditRevisionRecord,
)
from kinocut.projectstore import layout, store
from kinocut.projectstore.cas import _deleted_digests

#: Default upper bound on total CAS blob bytes before GC evicts unreachable blobs.
DEFAULT_GC_BUDGET_BYTES = 20 * (1 << 30)  # 20 GiB
#: Evict oldest unreachable blobs until total bytes reach this fraction of the budget.
_GC_TARGET_FRACTION = 0.8


def _reachable_digests(project: store.Project) -> set[str]:
    """Derive reachable blob digests from each active edit-project head revision.

    A digest is reachable when it appears among the ``operation_ids`` of the
    single head revision for an edit project. Ambiguous heads (more than one
    unsuperseded record per identity) or corrupt heads (a ``head_revision_id``
    resolving to zero/multiple revisions) fail closed rather than risk evicting
    live data.
    """

    by_id: dict[str, list[EditProjectRecord]] = {}
    for record in store.read_records(project, "edit_project"):
        by_id.setdefault(record.edit_project_id, []).append(record)
    head_revision_ids: set[str] = set()
    for records in by_id.values():
        superseded = {r.supersedes for r in records if r.supersedes}
        heads = [r for r in records if r.record_id not in superseded]
        if len(heads) != 1:
            raise contract_error("edit project has an ambiguous head", INVALID_RECORD)
        if heads[0].head_revision_id is not None:
            head_revision_ids.add(heads[0].head_revision_id)
    by_rev: dict[str, list[EditRevisionRecord]] = {}
    for record in store.read_records(project, "edit_revision"):
        by_rev.setdefault(record.record_id, []).append(record)
    reachable: set[str] = set()
    for head_rev_id in head_revision_ids:
        matches = by_rev.get(head_rev_id, [])
        if len(matches) != 1:
            raise contract_error("edit project head references an invalid revision", INVALID_RECORD)
        reachable.update(matches[0].operation_ids)
    return reachable


def collect_cas_garbage(
    project: store.Project,
    *,
    budget_bytes: int = DEFAULT_GC_BUDGET_BYTES,
) -> CASGCReceiptRecord | None:
    """Delete oldest unreachable CAS blobs over an explicit byte budget.

    Reachable blobs (referenced by an active head revision) are never deleted.
    When total live blob bytes exceed ``budget_bytes`` the oldest unreachable
    manifests — in append order — are evicted until the total falls to 80% of the
    budget, then a canonical append-only ``cas_gc`` receipt records the deleted
    digests, freed bytes, and retained reachable count. Under budget (or with no
    unreachable candidate to evict) this is a no-op that persists nothing and
    returns ``None``.
    """

    if budget_bytes < 0:
        raise contract_error("CAS GC budget must be non-negative", INVALID_RECORD)
    with store._project_lock(project):
        already_deleted = _deleted_digests(project)  # prior append-only GC receipts
        alive = [
            r
            for r in store.read_records(project, "cas_manifest")
            if isinstance(r, CASManifestRecord) and r.digest not in already_deleted
        ]
        reachable = _reachable_digests(project)
        unreachable = [m for m in alive if m.digest not in reachable]
        retained_reachable = sum(1 for m in alive if m.digest in reachable)
        total = sum(m.byte_size for m in alive)
        target = int(budget_bytes * _GC_TARGET_FRACTION)
        to_delete: list[CASManifestRecord] = []
        if total > budget_bytes:
            for manifest in unreachable:  # oldest first (manifest append order)
                if total <= target:
                    break
                to_delete.append(manifest)
                total -= manifest.byte_size
        if not to_delete:
            return None
        with store._mapped_os_errors():
            for manifest in to_delete:
                store.safe_target(project, layout.blob_relative_path(manifest.digest)).unlink(missing_ok=True)
        receipt = validate_record(
            CASGCReceiptRecord,
            {
                "project_id": project.project_id,
                "created_by": "tool",
                "budget_bytes": budget_bytes,
                "deleted_digests": tuple(m.digest for m in to_delete),
                "deleted_bytes": sum(m.byte_size for m in to_delete),
                "retained_reachable": retained_reachable,
            },
        )
        return cast(CASGCReceiptRecord, store.append_record_locked(project, receipt))


__all__ = ["DEFAULT_GC_BUDGET_BYTES", "collect_cas_garbage"]
