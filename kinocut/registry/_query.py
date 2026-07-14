"""Approved-clip and reusable-bed query APIs over the project store.

These read-only queries compose the durable registry records (``ClipRecord``,
``BedRecord``) with the verdict, rights, and consent records already in the
project store. They never mutate state, never load whole files into memory, and
return deterministically ordered, paginated results suitable for later semantic
and beat-planning layers.

Filtering policy (design §4.4 / §4.9):

* **Verdict** — only clips whose bound ``ClipVerdict`` has an approved
  disposition (``approved`` or ``approved_with_trim``) enter the result.
* **Rights** — only clips/beds whose ``usage_rights_status`` is ``cleared``
  by default; a caller may widen the filter with ``rights_filter``.
* **Consent** — only clips/beds whose ``review_decision_id`` resolves to a
  fresh human ``approve`` decision bound to the clip/bed asset enter the result.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.asset import AssetRecord, UsageRightsStatus
from kinocut.contracts.review import DecisionType, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict
from kinocut.projectstore.store import Project, read_records
from kinocut.errors import MCPVideoError
from kinocut.contracts.registry import BedRecord, ClipRecord

#: The default rights posture required to enter an approved-only result.
_DEFAULT_RIGHTS = frozenset({UsageRightsStatus.CLEARED})

#: Maximum page size to prevent unbounded reads.
_MAX_LIMIT = 500


@dataclass(frozen=True)
class QueryPage:
    """One deterministically ordered, paginated slice of registry records."""

    records: tuple[ClipRecord | BedRecord, ...]
    total: int
    offset: int
    limit: int


def _validate_pagination(limit: int, offset: int) -> None:
    """Enforce bounded, non-negative pagination parameters."""

    if isinstance(limit, bool) or not isinstance(limit, int):
        raise MCPVideoError("limit must be an integer", error_type="validation_error", code="invalid_pagination")
    if isinstance(offset, bool) or not isinstance(offset, int):
        raise MCPVideoError("offset must be an integer", error_type="validation_error", code="invalid_pagination")
    if limit < 1:
        raise MCPVideoError("limit must be at least one", error_type="validation_error", code="invalid_pagination")
    if limit > _MAX_LIMIT:
        raise MCPVideoError(
            f"limit must not exceed {_MAX_LIMIT}", error_type="validation_error", code="invalid_pagination"
        )
    if offset < 0:
        raise MCPVideoError("offset must be non-negative", error_type="validation_error", code="invalid_pagination")


def _active_records(project: Project, kind: str, model: type) -> list:
    """Return only unsuperseded records of the exact expected type."""

    records = [record for record in read_records(project, kind) if type(record) is model]
    superseded = {record.supersedes for record in records if record.supersedes is not None}
    return [record for record in records if canonical_record_id(record) not in superseded]


def _index_active_assets(project: Project) -> dict[str, AssetRecord]:
    """Index uniquely active asset records, omitting ambiguous asset identities."""

    indexed: dict[str, AssetRecord] = {}
    ambiguous: set[str] = set()
    for asset in _active_records(project, "asset_record", AssetRecord):
        if asset.asset_id in indexed:
            indexed.pop(asset.asset_id)
            ambiguous.add(asset.asset_id)
        elif asset.asset_id not in ambiguous:
            indexed[asset.asset_id] = asset
    return indexed


def _active_asset_rights_allowed(
    asset_id: str, assets: dict[str, AssetRecord], rights: frozenset[UsageRightsStatus]
) -> bool:
    """Require one active asset record whose current rights are allowed."""

    asset = assets.get(asset_id)
    return asset is not None and asset.usage_rights_status in rights


def _index_verdicts(project: Project) -> dict[str, ClipVerdict]:
    """Return a canonical-id → verdict index of all clip verdicts."""

    return {canonical_record_id(verdict): verdict for verdict in _active_records(project, "clip_verdict", ClipVerdict)}


def _index_decisions(project: Project) -> dict[str, ReviewDecision]:
    """Return a canonical-id → decision index of all review decisions."""

    return {
        canonical_record_id(decision): decision
        for decision in _active_records(project, "review_decision", ReviewDecision)
    }


def _verdict_is_approved(verdict: ClipVerdict | None) -> bool:
    """True when a verdict exists and has an approved disposition."""

    return verdict is not None and verdict.enters_approved_search()


def _consent_is_valid(
    decision: ReviewDecision | None,
    *,
    target_asset: str,
) -> bool:
    """True when a fresh human approve targets the given asset."""

    if decision is None:
        return False
    if type(decision) is not ReviewDecision:
        return False
    if decision.record_id is not None and decision.record_id != canonical_record_id(decision):
        return False
    if decision.decision is not DecisionType.APPROVE:
        return False
    if decision.actor != "human" or not decision.created_by.startswith("human"):
        return False
    return decision.target_ref == target_asset


def _matches_tags(tags: tuple[str, ...], wanted: frozenset[str] | None) -> bool:
    """True when every wanted tag is present on the record (AND semantics)."""

    if wanted is None:
        return True
    return wanted.issubset(set(tags))


def query_approved_clips(
    project: Project,
    *,
    tags: Iterable[str] | None = None,
    rights_filter: Iterable[UsageRightsStatus] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> QueryPage:
    """Return approved clips filtered by verdict, rights, consent, and tags.

    Ordering is deterministic: records are sorted by their canonical
    ``record_id`` (a content-addressed digest), so the same store always yields
    the same order. Pagination is stable: ``(limit, offset)`` slices the sorted
    full match list.
    """

    _validate_pagination(limit, offset)
    wanted = frozenset(tags) if tags is not None else None
    rights = _rights_or_default(rights_filter)
    verdicts = _index_verdicts(project)
    decisions = _index_decisions(project)
    assets = _index_active_assets(project)

    all_clips = _active_records(project, "clip_record", ClipRecord)
    matched = [
        clip
        for clip in all_clips
        if clip.usage_rights_status in rights
        and _active_asset_rights_allowed(clip.asset_id, assets, rights)
        and _active_asset_rights_allowed(clip.source_asset_id, assets, rights)
        and _verdict_is_approved(verdicts.get(clip.verdict_id))
        and _consent_is_valid(decisions.get(clip.review_decision_id), target_asset=clip.asset_id)
        and _matches_tags(clip.tags, wanted)
    ]
    return _paginate(matched, limit, offset, key=lambda clip: clip.record_id)


def query_reusable_beds(
    project: Project,
    *,
    tags: Iterable[str] | None = None,
    mood: str | None = None,
    rights_filter: Iterable[UsageRightsStatus] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> QueryPage:
    """Return reusable beds filtered by rights, consent, tags, and mood."""

    _validate_pagination(limit, offset)
    wanted = frozenset(tags) if tags is not None else None
    assets = _index_active_assets(project)
    rights = _rights_or_default(rights_filter)
    decisions = _index_decisions(project)

    all_beds = _active_records(project, "bed_record", BedRecord)
    matched = [
        bed
        for bed in all_beds
        if bed.usage_rights_status in rights
        and _active_asset_rights_allowed(bed.asset_id, assets, rights)
        and _consent_is_valid(decisions.get(bed.review_decision_id), target_asset=bed.asset_id)
        and _matches_tags(bed.tags, wanted)
        and (mood is None or bed.mood == mood)
    ]
    return _paginate(matched, limit, offset, key=lambda bed: bed.record_id)


def _rights_or_default(
    rights_filter: Iterable[UsageRightsStatus] | None,
) -> frozenset[UsageRightsStatus]:
    """Return the caller's rights filter, or the default cleared-only set."""

    if rights_filter is None:
        return _DEFAULT_RIGHTS
    return frozenset(rights_filter)


def _paginate(
    records: list[ClipRecord | BedRecord],
    limit: int,
    offset: int,
    *,
    key,
) -> QueryPage:
    """Sort by ``key``, slice, and return a page with total count."""

    records.sort(key=key)
    total = len(records)
    page = tuple(records[offset : offset + limit])
    return QueryPage(records=page, total=total, offset=offset, limit=limit)
