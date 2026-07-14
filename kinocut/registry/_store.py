"""Write-time referential validation for registry records.

The project store already guarantees atomicity, locking, canonical ids, and
fail-closed tamper detection. This thin layer adds **referential integrity** at
the write boundary: a ``ClipRecord`` may not reference a verdict or review
decision that does not exist in the same project; a ``LineageLink`` may not
reference an unknown asset. This keeps the durable registry free of dangling
references without duplicating any storage, hashing, or path-safety logic.

All reads needed for validation are performed inside the same project-lock
transaction as the append (via ``append_record_locked``), so a concurrent
delete/supersession cannot split the check from the write.
"""

from __future__ import annotations

from typing import cast

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.review import ReviewDecision
from kinocut.contracts.verdict import ClipVerdict
from kinocut.projectstore.store import (
    Project,
    append_record_locked,
    read_records,
)
from kinocut.contracts.registry import BedRecord, ClipRecord, LineageLink


def register_clip(project: Project, record: ClipRecord) -> ClipRecord:
    """Validate references then append a ``ClipRecord`` atomically.

    Requires that the bound verdict exists in the same project, that the
    review-decision reference exists, and that the source asset exists.
    Verdict disposition filtering is the query layer's responsibility. The check
    and the append run in one lock transaction.
    """

    from kinocut.projectstore import store as _store

    with _store._project_lock(project):
        _validate_clip_refs(project, record)
        result = append_record_locked(project, record)
    return cast(ClipRecord, result)


def register_bed(project: Project, record: BedRecord) -> BedRecord:
    """Validate the consent reference then append a ``BedRecord`` atomically."""

    from kinocut.projectstore import store as _store

    with _store._project_lock(project):
        _validate_bed_refs(project, record)
        result = append_record_locked(project, record)
    return cast(BedRecord, result)


def register_lineage(project: Project, record: LineageLink) -> LineageLink:
    """Validate asset references then append a ``LineageLink`` atomically."""

    from kinocut.projectstore import store as _store

    with _store._project_lock(project):
        _validate_lineage_refs(project, record)
        result = append_record_locked(project, record)
    return cast(LineageLink, result)


def _validate_clip_refs(project: Project, record: ClipRecord) -> None:
    """Fail closed if the verdict, consent, or source asset is missing.

    Referential integrity only — verdict *disposition* filtering is the query
    layer's responsibility (:func:`query_approved_clips`). This allows a clip to
    be registered before the verdict is finalized and reflects verdict
    supersession naturally through the query layer.
    """

    _check_same_project(record.project_id, project)
    _find_record_by_id(read_records(project, "clip_verdict"), record.verdict_id, ClipVerdict, "clip verdict")
    _find_record_by_id(
        read_records(project, "review_decision"),
        record.review_decision_id,
        ReviewDecision,
        "review decision",
    )
    _find_asset(project, record.source_asset_id, "source asset")
    if record.asset_id != record.source_asset_id:
        _find_asset(project, record.asset_id, "clip asset")


def _validate_bed_refs(project: Project, record: BedRecord) -> None:
    """Fail closed if the consent reference or bed asset is missing."""

    _check_same_project(record.project_id, project)
    _find_record_by_id(
        read_records(project, "review_decision"),
        record.review_decision_id,
        ReviewDecision,
        "review decision",
    )
    _find_asset(project, record.asset_id, "bed asset")


def _validate_lineage_refs(project: Project, record: LineageLink) -> None:
    """Fail closed if any referenced asset is unknown."""

    _check_same_project(record.project_id, project)
    known = _known_asset_ids(project)
    for asset_id in (record.derivative_asset_id, *record.source_asset_ids):
        if asset_id not in known:
            raise contract_error("lineage link references an unknown asset", INVALID_RECORD)


def _check_same_project(record_project_id: str, project: Project) -> None:
    """Reject a record that belongs to a different project store."""

    if record_project_id != project.project_id:
        raise contract_error("record belongs to another project store", INVALID_RECORD)


def _find_record_by_id(records, target_id: str, model_cls, label: str):
    """Return the one record whose canonical id matches ``target_id``."""

    for record in records:
        if canonical_record_id(record) == target_id:
            if type(record) is not model_cls:
                raise contract_error(f"referenced {label} is the wrong record type", INVALID_RECORD)
            return record
    raise contract_error(f"referenced {label} does not exist", INVALID_RECORD)


def _find_asset(project: Project, asset_id: str, label: str) -> AssetRecord:
    """Return the one asset record matching ``asset_id``, or fail closed."""

    for record in read_records(project, "asset_record"):
        if not isinstance(record, AssetRecord):
            continue
        if record.asset_id == asset_id:
            return record
    raise contract_error(f"referenced {label} does not exist", INVALID_RECORD)


def _known_asset_ids(project: Project) -> frozenset[str]:
    """Return the set of all known asset ids in the project store."""

    return frozenset(
        record.asset_id for record in read_records(project, "asset_record") if isinstance(record, AssetRecord)
    )
