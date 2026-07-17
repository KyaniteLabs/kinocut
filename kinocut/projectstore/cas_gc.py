"""Bounded CAS reachability accounting and garbage collection."""

from __future__ import annotations

from typing import cast

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import (
    CASGCReceiptRecord,
    CASManifestRecord,
    BranchRecord,
    EditProjectRecord,
    EditRevisionRecord,
    RevisionSourcesRecord,
)
from kinocut.projectstore import layout, store
from kinocut.projectstore.cas import _deleted_digests

#: Default upper bound on total CAS blob bytes before GC evicts unreachable blobs.
DEFAULT_GC_BUDGET_BYTES = 20 * (1 << 30)  # 20 GiB
#: Evict oldest unreachable blobs until total bytes reach this fraction of the budget.
_GC_TARGET_FRACTION = 0.8


def _reachable_digests(project: store.Project) -> set[str]:
    """Resolve source CAS digests across every branch and crash-recovery head."""
    project_heads: dict[str, str | None] = {}
    by_project: dict[str, list[EditProjectRecord]] = {}
    for record in store.read_records(project, "edit_project"):
        by_project.setdefault(record.edit_project_id, []).append(record)
    for edit_project_id, records in by_project.items():
        superseded = {record.supersedes for record in records if record.supersedes}
        heads = [record for record in records if record.record_id not in superseded]
        if len(heads) != 1:
            raise contract_error("edit project has an ambiguous head", INVALID_RECORD)
        project_heads[edit_project_id] = heads[0].head_revision_id

    branch_heads: dict[tuple[str, str], str | None] = {}
    by_branch: dict[tuple[str, str], list[BranchRecord]] = {}
    for record in store.read_records(project, "branch"):
        by_branch.setdefault((record.edit_project_id, record.branch_name), []).append(record)
    for key, records in by_branch.items():
        superseded = {record.supersedes for record in records if record.supersedes}
        heads = [record for record in records if record.record_id not in superseded]
        if len(heads) != 1:
            raise contract_error("branch has an ambiguous head", INVALID_RECORD)
        branch_heads[key] = heads[0].head_revision_id
    for edit_project_id, head in project_heads.items():
        branch_heads.setdefault((edit_project_id, "main"), head)

    revisions: dict[str, EditRevisionRecord] = {}
    for record in store.read_records(project, "edit_revision"):
        if record.record_id in revisions:
            raise contract_error("duplicate revision identity", INVALID_RECORD)
        revisions[record.record_id] = record
    if any(head is not None and head not in revisions for head in project_heads.values()):
        raise contract_error("edit project head references an invalid revision", INVALID_RECORD)

    source_records: dict[str, RevisionSourcesRecord] = {}
    for record in store.read_records(project, "revision_sources"):
        if record.revision_id in source_records:
            raise contract_error("duplicate revision source mapping", INVALID_RECORD)
        if record.revision_id not in revisions:
            raise contract_error("revision source mapping references a missing revision", INVALID_RECORD)
        source_records[record.revision_id] = record
    manifest_digests = {
        record.digest for record in store.read_records(project, "cas_manifest") if isinstance(record, CASManifestRecord)
    }

    reachable: set[str] = set()
    roots = set(branch_heads.values()) | set(project_heads.values())
    for head_revision_id in roots:
        seen: set[str] = set()
        revision_id = head_revision_id
        while revision_id is not None:
            if revision_id in seen or revision_id not in revisions:
                raise contract_error("branch head references an invalid revision graph", INVALID_RECORD)
            seen.add(revision_id)
            revision = revisions[revision_id]
            sources = source_records.get(revision_id)
            if sources is not None:
                reachable.update(sources.source_digests)
            else:
                direct_digests = set(revision.operation_ids) & manifest_digests
                reachable.update(direct_digests)
                if len(direct_digests) != len(set(revision.operation_ids)):
                    # Legacy opaque operation hashes cannot be resolved to their source
                    # blobs. Conservatively retain the store rather than risk data loss.
                    reachable.update(manifest_digests)
            revision_id = revision.parent_revision_id
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
