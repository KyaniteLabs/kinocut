"""Query-API tests: verdict/rights/consent filtering, pagination, determinism.

Tests the approved-clip and reusable-bed query layers over a fully seeded
project store, covering: revoked rights, rejected verdict, missing consent,
tag filtering, mood filtering, deterministic ordering, and stable pagination.
"""

from __future__ import annotations

import pytest

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.asset import (
    AssetRecord,
)
from kinocut.contracts.registry import BedRecord, ClipRecord
from kinocut.contracts.review import ReviewDecision
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.projectstore import append_record, open_project
from kinocut.errors import MCPVideoError
from kinocut.registry import (
    query_approved_clips,
    query_reusable_beds,
    register_bed,
    register_clip,
)
from tests.contracts_fixtures import (
    asset_record_kwargs,
    review_decision_kwargs,
    verdict_kwargs,
)
from tests.registry_fixtures import bed_record_kwargs, clip_record_kwargs

_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64


def _seed_asset(project, asset_id: str) -> AssetRecord:
    return append_record(
        project,
        AssetRecord(
            **asset_record_kwargs(
                project_id=project.project_id,
                asset_id=asset_id,
                original_location=f"inputs/{asset_id[:12]}.mp4",
                lineage=None,
            )
        ),
    )


def _seed_verdict(project, asset_hash: str, disposition: Disposition = Disposition.APPROVED) -> str:
    verdict = append_record(
        project,
        ClipVerdict(
            **verdict_kwargs(
                project_id=project.project_id,
                asset_hash=asset_hash,
                disposition=disposition.value,
                acceptance_spec_id=_SHA,
            )
        ),
    )
    return canonical_record_id(verdict)


def _seed_decision(project, target_ref: str, decision: str = "approve") -> str:
    rd = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=target_ref,
                decision=decision,
            )
        ),
    )
    return canonical_record_id(rd)


def _make_clip(
    project,
    asset_id: str,
    verdict_id: str,
    decision_id: str,
    rights: str = "cleared",
    tags=(),
    **overrides,
) -> ClipRecord:
    kwargs = clip_record_kwargs(
        project_id=project.project_id,
        asset_id=asset_id,
        source_asset_id=asset_id,
        verdict_id=verdict_id,
        review_decision_id=decision_id,
        usage_rights_status=rights,
        tags=tags,
    )
    kwargs.update(overrides)
    return register_clip(project, ClipRecord(**kwargs))


def _make_bed(
    project,
    asset_id: str,
    decision_id: str,
    rights: str = "cleared",
    mood="upbeat",
    tags=(),
    **overrides,
) -> BedRecord:
    kwargs = bed_record_kwargs(
        project_id=project.project_id,
        asset_id=asset_id,
        review_decision_id=decision_id,
        usage_rights_status=rights,
        mood=mood,
        tags=tags,
    )
    kwargs.update(overrides)
    return register_bed(project, BedRecord(**kwargs))


# ---- Approved-clip query -------------------------------------------------


def test_query_approved_clips_empty_when_no_records(tmp_path):
    proj = open_project(tmp_path / "proj")
    page = query_approved_clips(proj)
    assert page.records == ()
    assert page.total == 0


def test_query_approved_clips_returns_approved_only(tmp_path):
    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    a2 = "sha256:" + "2" * 64
    for aid in (a1, a2):
        _seed_asset(proj, aid)
    v1 = _seed_verdict(proj, a1, Disposition.APPROVED)
    v2 = _seed_verdict(proj, a2, Disposition.REJECTED)
    d1 = _seed_decision(proj, a1)
    d2 = _seed_decision(proj, a2)
    _make_clip(proj, a1, v1, d1)
    _make_clip(proj, a2, v2, d2)  # rejected verdict
    page = query_approved_clips(proj)
    assert page.total == 1
    assert page.records[0].asset_id == a1


def test_query_filters_revoked_rights(tmp_path):
    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    a2 = "sha256:" + "2" * 64
    for aid in (a1, a2):
        _seed_asset(proj, aid)
    v1 = _seed_verdict(proj, a1)
    v2 = _seed_verdict(proj, a2)
    d1 = _seed_decision(proj, a1)
    d2 = _seed_decision(proj, a2)
    _make_clip(proj, a1, v1, d1, rights="cleared")
    _make_clip(proj, a2, v2, d2, rights="restricted")
    page = query_approved_clips(proj)
    assert page.total == 1
    assert page.records[0].asset_id == a1


def test_query_filters_by_consent(tmp_path):
    """A clip whose review decision is a reject is excluded."""

    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    a2 = "sha256:" + "2" * 64
    for aid in (a1, a2):
        _seed_asset(proj, aid)
    v1 = _seed_verdict(proj, a1)
    v2 = _seed_verdict(proj, a2)
    d1 = _seed_decision(proj, a1, decision="approve")
    d2 = _seed_decision(proj, a2, decision="reject")
    _make_clip(proj, a1, v1, d1)
    _make_clip(proj, a2, v2, d2)
    page = query_approved_clips(proj)
    assert page.total == 1
    assert page.records[0].asset_id == a1


def test_query_consent_must_target_clip_asset(tmp_path):
    """A decision targeting a different asset is not valid consent."""

    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    other = "sha256:" + "9" * 64
    _seed_asset(proj, a1)
    v1 = _seed_verdict(proj, a1)
    d_wrong = _seed_decision(proj, other)  # targets "other", not a1
    _make_clip(proj, a1, v1, d_wrong)
    page = query_approved_clips(proj)
    assert page.total == 0


def test_query_filters_by_tags(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i in range(5):
        aid = "sha256:" + f"{i + 1}" * 64
        _seed_asset(proj, aid)
        vi = _seed_verdict(proj, aid)
        di = _seed_decision(proj, aid)
        tag_set = ("intro",) if i < 2 else ("cta",)
        _make_clip(proj, aid, vi, di, tags=tag_set)
    page = query_approved_clips(proj, tags=("intro",))
    assert page.total == 2
    assert all("intro" in clip.tags for clip in page.records)


def test_query_pagination(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i in range(10):
        aid = "sha256:" + f"{i + 1:064d}"
        # Fix: need exactly 64 hex chars after sha256:
        aid = "sha256:" + str(i + 1) * 64
        aid = aid[:71]  # sha256: + 64 chars
        _seed_asset(proj, aid)
        vi = _seed_verdict(proj, aid)
        di = _seed_decision(proj, aid)
        _make_clip(proj, aid, vi, di)
    page1 = query_approved_clips(proj, limit=3, offset=0)
    page2 = query_approved_clips(proj, limit=3, offset=3)
    assert page1.total == 10
    assert len(page1.records) == 3
    assert len(page2.records) == 3
    # No overlap.
    ids1 = {r.record_id for r in page1.records}
    ids2 = {r.record_id for r in page2.records}
    assert ids1.isdisjoint(ids2)


def test_query_deterministic_order(tmp_path):
    """Same store → same order every time, by canonical record_id."""

    proj = open_project(tmp_path / "proj")
    for i in range(6):
        aid = "sha256:" + str(i + 1) * 64
        _seed_asset(proj, aid)
        vi = _seed_verdict(proj, aid)
        di = _seed_decision(proj, aid)
        _make_clip(proj, aid, vi, di)
    p1 = query_approved_clips(proj)
    p2 = query_approved_clips(proj)
    assert [r.record_id for r in p1.records] == [r.record_id for r in p2.records]
    # Verify sorted by record_id.
    ids = [r.record_id for r in p1.records]
    assert ids == sorted(ids)


def test_query_pagination_validation(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError):
        query_approved_clips(proj, limit=0)
    with pytest.raises(MCPVideoError):
        query_approved_clips(proj, offset=-1)
    with pytest.raises(MCPVideoError):
        query_approved_clips(proj, limit=99999)


def test_query_excludes_clip_when_approval_is_superseded(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "1" * 64
    _seed_asset(proj, asset_id)
    verdict_id = _seed_verdict(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_clip(proj, asset_id, verdict_id, approval_id)
    append_record(
        proj,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=proj.project_id,
                target_ref=asset_id,
                decision="reject",
            ),
            supersedes=approval_id,
        ),
    )

    assert query_approved_clips(proj).total == 0


def test_query_excludes_clip_when_verdict_is_superseded(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "2" * 64
    _seed_asset(proj, asset_id)
    verdict_id = _seed_verdict(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_clip(proj, asset_id, verdict_id, approval_id)
    append_record(
        proj,
        ClipVerdict(
            **verdict_kwargs(
                project_id=proj.project_id,
                asset_hash=asset_id,
                disposition=Disposition.REJECTED.value,
                acceptance_spec_id=_SHA,
            ),
            supersedes=verdict_id,
        ),
    )

    assert query_approved_clips(proj).total == 0


def test_query_uses_only_active_clip_record(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "3" * 64
    _seed_asset(proj, asset_id)
    verdict_id = _seed_verdict(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    original = _make_clip(proj, asset_id, verdict_id, approval_id)
    _make_clip(
        proj,
        asset_id,
        verdict_id,
        approval_id,
        rights="restricted",
        supersedes=original.record_id,
    )

    assert query_approved_clips(proj).total == 0


def test_query_excludes_clip_when_active_asset_rights_are_restricted(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "5" * 64
    asset = _seed_asset(proj, asset_id)
    verdict_id = _seed_verdict(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_clip(proj, asset_id, verdict_id, approval_id)
    append_record(
        proj,
        AssetRecord(
            **asset_record_kwargs(
                project_id=proj.project_id,
                asset_id=asset_id,
                original_location=asset.original_location,
                usage_rights_status="restricted",
                lineage=None,
            ),
            supersedes=asset.record_id,
        ),
    )

    assert query_approved_clips(proj).total == 0


def test_query_excludes_clip_when_source_asset_rights_are_restricted(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "7" * 64
    source_id = "sha256:" + "8" * 64
    _seed_asset(proj, asset_id)
    source = _seed_asset(proj, source_id)
    verdict_id = _seed_verdict(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_clip(proj, asset_id, verdict_id, approval_id, source_asset_id=source_id)
    append_record(
        proj,
        AssetRecord(
            **asset_record_kwargs(
                project_id=proj.project_id,
                asset_id=source_id,
                original_location=source.original_location,
                usage_rights_status="restricted",
                lineage=None,
            ),
            supersedes=source.record_id,
        ),
    )

    assert query_approved_clips(proj).total == 0


def test_query_excludes_bed_when_active_asset_rights_are_restricted(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "6" * 64
    asset = _seed_asset(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_bed(proj, asset_id, approval_id)
    append_record(
        proj,
        AssetRecord(
            **asset_record_kwargs(
                project_id=proj.project_id,
                asset_id=asset_id,
                original_location=asset.original_location,
                usage_rights_status="restricted",
                lineage=None,
            ),
            supersedes=asset.record_id,
        ),
    )

    assert query_reusable_beds(proj).total == 0


def test_query_excludes_bed_when_approval_is_superseded(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset_id = "sha256:" + "4" * 64
    _seed_asset(proj, asset_id)
    approval_id = _seed_decision(proj, asset_id)
    _make_bed(proj, asset_id, approval_id)
    append_record(
        proj,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=proj.project_id,
                target_ref=asset_id,
                decision="reject",
            ),
            supersedes=approval_id,
        ),
    )

    assert query_reusable_beds(proj).total == 0


# ---- Reusable-bed query --------------------------------------------------


def test_query_reusable_beds_empty_when_no_records(tmp_path):
    proj = open_project(tmp_path / "proj")
    page = query_reusable_beds(proj)
    assert page.records == ()
    assert page.total == 0


def test_query_beds_filters_by_rights(tmp_path):
    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    a2 = "sha256:" + "2" * 64
    for aid in (a1, a2):
        _seed_asset(proj, aid)
    d1 = _seed_decision(proj, a1)
    d2 = _seed_decision(proj, a2)
    _make_bed(proj, a1, d1, rights="cleared")
    _make_bed(proj, a2, d2, rights="restricted")
    page = query_reusable_beds(proj)
    assert page.total == 1
    assert page.records[0].asset_id == a1


def test_query_beds_filters_by_consent(tmp_path):
    proj = open_project(tmp_path / "proj")
    a1 = "sha256:" + "1" * 64
    a2 = "sha256:" + "2" * 64
    for aid in (a1, a2):
        _seed_asset(proj, aid)
    d1 = _seed_decision(proj, a1, decision="approve")
    d2 = _seed_decision(proj, a2, decision="reject")
    _make_bed(proj, a1, d1)
    _make_bed(proj, a2, d2)
    page = query_reusable_beds(proj)
    assert page.total == 1


def test_query_beds_filters_by_mood(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i, mood in enumerate(("upbeat", "calm", "upbeat")):
        aid = "sha256:" + str(i + 1) * 64
        _seed_asset(proj, aid)
        di = _seed_decision(proj, aid)
        _make_bed(proj, aid, di, mood=mood)
    page = query_reusable_beds(proj, mood="upbeat")
    assert page.total == 2
    assert all(bed.mood == "upbeat" for bed in page.records)


def test_query_beds_filters_by_tags(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i in range(4):
        aid = "sha256:" + str(i + 1) * 64
        _seed_asset(proj, aid)
        di = _seed_decision(proj, aid)
        tags = ("electronic",) if i < 2 else ("acoustic",)
        _make_bed(proj, aid, di, tags=tags)
    page = query_reusable_beds(proj, tags=("electronic",))
    assert page.total == 2


def test_query_beds_deterministic_order(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i in range(5):
        aid = "sha256:" + str(i + 1) * 64
        _seed_asset(proj, aid)
        di = _seed_decision(proj, aid)
        _make_bed(proj, aid, di)
    p1 = query_reusable_beds(proj)
    p2 = query_reusable_beds(proj)
    assert [r.record_id for r in p1.records] == [r.record_id for r in p2.records]
    ids = [r.record_id for r in p1.records]
    assert ids == sorted(ids)


def test_query_beds_pagination(tmp_path):
    proj = open_project(tmp_path / "proj")
    for i in range(8):
        aid = "sha256:" + str(i + 1) * 64
        _seed_asset(proj, aid)
        di = _seed_decision(proj, aid)
        _make_bed(proj, aid, di)
    page = query_reusable_beds(proj, limit=3, offset=0)
    assert page.total == 8
    assert len(page.records) == 3
    page2 = query_reusable_beds(proj, limit=3, offset=3)
    assert len(page2.records) == 3
    ids1 = {r.record_id for r in page.records}
    ids2 = {r.record_id for r in page2.records}
    assert ids1.isdisjoint(ids2)
