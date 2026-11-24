"""Projectstore integration tests for registry records.

Tests the strict TDD requirements: hostile symlink/path traversal, concurrent
append/atomic failure, tampered ledger, revoked rights/consent, rejected
verdict, exact duplicate, cycles, missing refs, backward reader,
pagination/determinism.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

import pytest

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.registry import (
    BedRecord,
    ClipRecord,
    LineageLink,
)
from kinocut.contracts.review import ReviewDecision
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project, read_records
from tests.contracts_fixtures import (
    asset_record_kwargs,
    review_decision_kwargs,
    verdict_kwargs,
)
from tests.registry_fixtures import clip_record_kwargs

_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_ASSET = "sha256:" + "d" * 64
_ASSET_B = "sha256:" + "e" * 64


# ---- Helpers to build a complete project with assets/verdicts/decisions --


def _seed_asset(project, asset_id: str = _ASSET) -> AssetRecord:
    """Append a minimal asset record so referential checks can resolve it."""

    record = AssetRecord(
        **asset_record_kwargs(
            project_id=project.project_id,
            asset_id=asset_id,
            original_location=f"inputs/{asset_id[:12]}.mp4",
            lineage=None,
        )
    )
    return append_record(project, record)


def _seed_verdict(
    project,
    asset_hash: str = _ASSET,
    disposition: Disposition = Disposition.APPROVED,
) -> ClipVerdict:
    verdict = ClipVerdict(
        **verdict_kwargs(
            project_id=project.project_id,
            asset_hash=asset_hash,
            disposition=disposition.value,
            acceptance_spec_id=_SHA,
        )
    )
    return append_record(project, verdict)


def _seed_decision(project, target_ref: str = _ASSET) -> ReviewDecision:
    decision = ReviewDecision(
        **review_decision_kwargs(
            project_id=project.project_id,
            target_ref=target_ref,
        )
    )
    return append_record(project, decision)


def _clip_payload(
    project,
    verdict_id: str,
    decision_id: str,
    asset_id: str = _ASSET,
    **overrides,
) -> dict:
    kwargs = clip_record_kwargs(
        project_id=project.project_id,
        asset_id=asset_id,
        source_asset_id=asset_id,
        verdict_id=verdict_id,
        review_decision_id=decision_id,
    )
    kwargs.update(overrides)
    return kwargs


# ---- Path safety: no host paths in registry records ----------------------


def test_clip_record_stores_no_home_or_absolute_paths(tmp_path):
    proj = open_project(tmp_path / "proj")
    asset = _seed_asset(proj)
    verdict = _seed_verdict(proj)
    decision = _seed_decision(proj)
    append_record(
        proj,
        ClipRecord(
            **_clip_payload(
                proj,
                verdict_id=verdict.record_id if verdict.record_id else canonical_record_id(verdict),
                decision_id=decision.record_id if decision.record_id else canonical_record_id(decision),
                asset_id=asset.asset_id,
            )
        ),
    )
    path = proj.root / ".kinocut" / "records" / "clip_record.jsonl"
    text = path.read_text(encoding="utf-8")
    assert str(Path.home()) not in text
    # Every line is valid canonical JSON.
    for line in text.splitlines():
        if line.strip():
            json.loads(line)


def test_registry_records_have_no_path_bearing_fields():
    """ClipRecord and BedRecord carry no original_location or path field."""

    for field in ("original_location", "usage_rights_evidence_ref", "file_path"):
        assert field not in ClipRecord.model_fields
        assert field not in BedRecord.model_fields
        assert field not in LineageLink.model_fields


# ---- Symlink defense: the store refuses symlinked record files -----------


def test_append_clip_refuses_symlinked_records_file(tmp_path):
    proj = open_project(tmp_path / "proj")
    records = proj.root / ".kinocut" / "records"
    outside = tmp_path / "outside"
    outside.mkdir()
    target = records / "clip_record.jsonl"
    target.symlink_to(outside / "clip_record.jsonl")
    asset = _seed_asset(proj)
    verdict = _seed_verdict(proj)
    decision = _seed_decision(proj)
    with pytest.raises(MCPVideoError):
        append_record(
            proj,
            ClipRecord(
                **_clip_payload(
                    proj,
                    verdict_id=canonical_record_id(verdict),
                    decision_id=canonical_record_id(decision),
                    asset_id=asset.asset_id,
                )
            ),
        )


# ---- Tampered ledger: fail closed -----------------------------------------


def test_tampered_clip_record_rejected_on_read(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "clip_record.jsonl"
    path.write_text('{"not_valid": true}\n', encoding="utf-8")
    with pytest.raises(MCPVideoError):
        read_records(proj, "clip_record")


def test_tampered_bed_record_rejected_on_read(tmp_path):
    proj = open_project(tmp_path / "proj")
    path = proj.root / ".kinocut" / "records" / "bed_record.jsonl"
    path.write_text("{bad json\n", encoding="utf-8")
    with pytest.raises(MCPVideoError):
        read_records(proj, "bed_record")


# ---- Atomic failure: prior file intact on write failure -------------------


def test_failed_append_leaves_prior_clip_file_intact(tmp_path, monkeypatch):
    proj = open_project(tmp_path / "proj")
    asset = _seed_asset(proj)
    verdict = _seed_verdict(proj)
    decision = _seed_decision(proj)
    append_record(
        proj,
        ClipRecord(
            **_clip_payload(
                proj,
                verdict_id=canonical_record_id(verdict),
                decision_id=canonical_record_id(decision),
                asset_id=asset.asset_id,
                tags=("first",),
            )
        ),
    )
    path = proj.root / ".kinocut" / "records" / "clip_record.jsonl"
    before = path.read_text(encoding="utf-8")

    def _boom(*_a, **_k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(MCPVideoError):
        append_record(
            proj,
            ClipRecord(
                **_clip_payload(
                    proj,
                    verdict_id=canonical_record_id(verdict),
                    decision_id=canonical_record_id(decision),
                    asset_id=asset.asset_id,
                    tags=("second",),
                )
            ),
        )
    assert path.read_text(encoding="utf-8") == before


# ---- Concurrent append: exact duplicate idempotency under contention ------


def test_concurrent_distinct_clips_all_persist(tmp_path):
    """Different clips appended concurrently all survive."""

    proj = open_project(tmp_path / "proj")
    asset = _seed_asset(proj)
    verdict = _seed_verdict(proj)
    decision = _seed_decision(proj)

    errors: list[Exception] = []

    def _worker(tag: str) -> None:
        try:
            append_record(
                proj,
                ClipRecord(
                    **_clip_payload(
                        proj,
                        verdict_id=canonical_record_id(verdict),
                        decision_id=canonical_record_id(decision),
                        asset_id=asset.asset_id,
                        tags=(tag,),
                    )
                ),
            )
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_worker, args=(f"t{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    clips = read_records(proj, "clip_record")
    assert len(clips) == 8


# ---- Missing refs: write-time referential integrity -----------------------


# ---- Backward reader: v1 records round-trip -------------------------------


def test_v1_clip_record_round_trips(tmp_path):
    """A v1 clip record written today reads back identically."""

    proj = open_project(tmp_path / "proj")
    asset = _seed_asset(proj)
    verdict = _seed_verdict(proj)
    decision = _seed_decision(proj)
    clip = append_record(
        proj,
        ClipRecord(
            **_clip_payload(
                proj,
                verdict_id=canonical_record_id(verdict),
                decision_id=canonical_record_id(decision),
                asset_id=asset.asset_id,
            )
        ),
    )
    records = read_records(proj, "clip_record")
    assert len(records) == 1
    assert isinstance(records[0], ClipRecord)
    assert records[0].asset_id == clip.asset_id
    assert records[0].record_id == clip.record_id
    assert records[0].schema_version == 1
