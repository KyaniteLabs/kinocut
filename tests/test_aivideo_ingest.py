"""Tests for the project ingest facade with generation metadata + rights (Plan 01 Task 5).

The facade extends the shipped content-addressed project store (no parallel
store): it copies the *immutable original* into the content-addressed store
before any normalization, is idempotent by byte digest on re-ingest, and records
strict generation lineage (model / provider / prompt-hash / settings-hash) plus a
rights posture that defaults to *unverified* with a private, project-relative
evidence reference. The original file is never mutated, and every filesystem
failure surfaces as a privacy-safe :class:`MCPVideoError`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kinocut.aivideo.ingest import ingest_project_asset
from kinocut.contracts.asset import (
    AssetRecord,
    GenerationLineage,
    MediaKind,
    UsageRightsStatus,
)
from kinocut.errors import MCPVideoError
from kinocut.projectstore import open_project, read_records

# sha256-shaped ids for lineage links and hashes (distinct from the ingested bytes).
_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_SOURCE_ASSET = "sha256:" + "c" * 64
_REFERENCE_ASSET = "sha256:" + "d" * 64


def _write_clip(path: Path, payload: bytes = b"\x00\x01clip-bytes\x02\x03") -> Path:
    path.write_bytes(payload)
    return path


def _lineage() -> GenerationLineage:
    return GenerationLineage(
        generator_model="veo-3",
        provider_id="provider-x",
        prompt_hash=_SHA,
        generation_settings_hash=_SHA_B,
        source_asset_ids=(_SOURCE_ASSET,),
        reference_asset_ids=(_REFERENCE_ASSET,),
    )


def test_copies_immutable_original_into_content_addressed_store(tmp_path):
    proj = open_project(tmp_path / "proj")
    payload = b"\x09\x08distinct-video-bytes"
    src = _write_clip(tmp_path / "movie.mp4", payload)
    rec = ingest_project_asset(proj, src)
    digest = rec.asset_id.split(":", 1)[1]
    stored = proj.root / ".kinocut" / "assets" / "sha256" / digest / "movie.mp4"
    assert stored.is_file()
    assert stored.read_bytes() == payload  # copied verbatim before any normalization


def test_asset_id_is_byte_hash_of_source(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(proj, src)
    assert isinstance(rec, AssetRecord)
    assert rec.asset_id == "sha256:" + hashlib.sha256(src.read_bytes()).hexdigest()
    assert rec.byte_size == src.stat().st_size
    assert rec.media_kind == MediaKind.VIDEO


def test_reingest_is_idempotent_by_digest(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    a = ingest_project_asset(proj, src, lineage=_lineage())
    b = ingest_project_asset(proj, src, lineage=_lineage())
    assert a.asset_id == b.asset_id
    stored = list((proj.root / ".kinocut" / "assets" / "sha256").glob("*/*"))
    assert len(stored) == 1  # bytes copied exactly once
    assert len(read_records(proj, "asset_record")) == 1  # one canonical record


def test_original_is_never_mutated(tmp_path):
    proj = open_project(tmp_path / "proj")
    payload = b"\x01original-untouched\x02"
    src = _write_clip(tmp_path / "clip.mp4", payload)
    ingest_project_asset(proj, src, lineage=_lineage())
    assert src.read_bytes() == payload  # source bytes unchanged by ingest


def test_records_strict_generation_metadata(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(proj, src, lineage=_lineage())
    assert rec.lineage is not None
    assert rec.lineage.generator_model == "veo-3"
    assert rec.lineage.provider_id == "provider-x"
    assert rec.lineage.prompt_hash == _SHA
    assert rec.lineage.generation_settings_hash == _SHA_B


def test_lineage_links_source_and_reference_assets(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(proj, src, lineage=_lineage())
    assert rec.lineage is not None
    assert rec.lineage.source_asset_ids == (_SOURCE_ASSET,)
    assert rec.lineage.reference_asset_ids == (_REFERENCE_ASSET,)


def test_rights_default_to_unverified(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(proj, src)
    assert rec.usage_rights_status is UsageRightsStatus.UNKNOWN
    assert rec.usage_rights_evidence_ref is None


def test_private_rights_evidence_reference_is_recorded(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(
        proj,
        src,
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )
    assert rec.usage_rights_status is UsageRightsStatus.PENDING
    assert rec.usage_rights_evidence_ref == "rights/clip.json"


def test_absolute_rights_evidence_reference_is_rejected(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    with pytest.raises(MCPVideoError):
        ingest_project_asset(proj, src, usage_rights_evidence_ref="/Users/someone/rights.json")


def test_enriched_record_persists_and_reads_back(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    ingest_project_asset(
        proj,
        src,
        lineage=_lineage(),
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )
    records = read_records(proj, "asset_record")
    assert len(records) == 1
    stored = records[0]
    assert isinstance(stored, AssetRecord)
    assert stored.lineage is not None
    assert stored.lineage.generator_model == "veo-3"
    assert stored.usage_rights_evidence_ref == "rights/clip.json"


def test_missing_source_raises_privacy_safe_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    with pytest.raises(MCPVideoError):
        ingest_project_asset(proj, tmp_path / "does-not-exist.mp4")


def test_record_leaks_no_absolute_host_path(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _write_clip(tmp_path / "clip.mp4")
    rec = ingest_project_asset(proj, src, lineage=_lineage())
    dumped = rec.model_dump_json()
    assert str(Path.home()) not in dumped
    assert str(tmp_path) not in dumped  # no absolute host path leaks into the record
