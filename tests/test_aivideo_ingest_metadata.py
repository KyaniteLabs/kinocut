"""Public ingest metadata boundary (Plan 01 Task 5 remediation).

Task 5's remediation moves the generation-lineage + rights logic *into* the
public :func:`kinocut.projectstore.ingest.ingest_asset`, and reduces the
``kinocut.aivideo`` facade to a thin delegating call. These tests pin that
boundary: the metadata kwargs are validated up front (even for a duplicate
ingest), a *plain* prior asset is enriched by an append-only superseding record,
identical metadata is idempotent, and conflicting metadata is rejected as a
privacy-safe :class:`MCPVideoError`.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kinocut.aivideo import ingest as aivideo_ingest
from kinocut.contracts.asset import (
    AssetRecord,
    GenerationLineage,
    MediaKind,
    UsageRightsStatus,
)
from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_record,
    ingest_asset,
    open_project,
    read_records,
)
from kinocut.projectstore.layout import asset_relative_path

_SHA = "sha256:" + "a" * 64


def _clip(path: Path, payload: bytes = b"\x00metadata-boundary\x01") -> Path:
    path.write_bytes(payload)
    return path


def _lineage() -> GenerationLineage:
    return GenerationLineage(generator_model="veo-3", provider_id="provider-x")


def test_facade_delegates_to_public_ingest_asset(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    def _spy(project, source_path, **kwargs):
        seen["project"] = project
        seen["source_path"] = Path(source_path)
        seen["kwargs"] = kwargs
        return "sentinel-record"

    # The facade must call the *public* ingest_asset it imported — patch that name.
    monkeypatch.setattr(aivideo_ingest, "ingest_asset", _spy)
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")

    out = aivideo_ingest.ingest_project_asset(
        proj,
        src,
        lineage=_lineage(),
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )

    assert out == "sentinel-record"
    assert seen["project"] is proj
    assert seen["source_path"] == Path(src)
    assert seen["kwargs"]["lineage"] == _lineage()
    assert seen["kwargs"]["usage_rights_status"] is UsageRightsStatus.PENDING
    assert seen["kwargs"]["usage_rights_evidence_ref"] == "rights/clip.json"


def test_invalid_runtime_lineage_is_private_error(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    # model_construct bypasses validation, so an ill-formed asset id only surfaces
    # at the store boundary — it must map to a privacy-safe MCPVideoError there.
    bad = GenerationLineage.model_construct(generator_model="m", provider_id="p", source_asset_ids=("not-a-sha",))
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src, lineage=bad)


def test_duplicate_bytes_still_validate_metadata(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(proj, src)  # plain original, already stored
    bad = GenerationLineage.model_construct(generator_model="m", provider_id="p", prompt_hash="not-a-hash")
    # Even though the bytes are a duplicate, invalid metadata is rejected up front
    # rather than silently short-circuiting to the stored record.
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src, lineage=bad)


def test_plain_prior_enriched_with_superseding_record(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    first = ingest_asset(proj, src)
    assert first.lineage is None

    second = ingest_asset(
        proj,
        src,
        lineage=_lineage(),
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )

    records = read_records(proj, "asset_record")
    assert len(records) == 2  # append-only: the plain original is retained
    assert second.supersedes == first.record_id
    assert second.asset_id == first.asset_id
    assert second.lineage == _lineage()
    assert second.usage_rights_status is UsageRightsStatus.PENDING
    assert second.usage_rights_evidence_ref == "rights/clip.json"
    # Bytes were never re-installed; the enriched record points at the same file.
    assert second.original_location == first.original_location


def test_identical_metadata_is_idempotent(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    a = ingest_asset(proj, src, lineage=_lineage(), usage_rights_status=UsageRightsStatus.PENDING)
    b = ingest_asset(proj, src, lineage=_lineage(), usage_rights_status=UsageRightsStatus.PENDING)
    assert a.record_id == b.record_id
    assert len(read_records(proj, "asset_record")) == 1  # no duplicate append


def test_conflicting_lineage_fails_private(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(proj, src, lineage=_lineage())
    other = GenerationLineage(generator_model="sora", provider_id="openai")
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src, lineage=other)


def test_conflicting_rights_evidence_fails_private(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(
        proj,
        src,
        usage_rights_status=UsageRightsStatus.CLEARED,
        usage_rights_evidence_ref="rights/a.json",
    )
    with pytest.raises(MCPVideoError):
        ingest_asset(
            proj,
            src,
            usage_rights_status=UsageRightsStatus.RESTRICTED,
            usage_rights_evidence_ref="rights/b.json",
        )


def test_malformed_lineage_inputs_are_private_errors_without_leak(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    marker = "TOPSECRET-9f8e7d-marker"
    # A raw, unvalidated dict carrying a secret in an unexpected field must never
    # be ``.model_dump()``-ed (that raised a raw ``AttributeError``); it maps to a
    # privacy-safe MCPVideoError and the secret is never echoed.
    malformed = {"generator_model": "m", "provider_id": "p", "leaked_field": marker}
    with pytest.raises(MCPVideoError) as dict_err:
        ingest_asset(proj, src, lineage=malformed)  # type: ignore[arg-type]
    assert marker not in str(dict_err.value)

    # An arbitrary object is likewise rejected as a stable MCPVideoError, not an
    # ``AttributeError`` from calling ``.model_dump()`` on a non-model.
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src, lineage=object())  # type: ignore[arg-type]


def test_repeat_enriched_ingest_returns_active_and_count_stays_two(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(proj, src)  # plain original
    enriched = ingest_asset(
        proj,
        src,
        lineage=_lineage(),
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )
    # Re-ingesting the *same* enriched metadata is idempotent against the active
    # (superseding) record — it must not enrich the already-enriched leaf again.
    again = ingest_asset(
        proj,
        src,
        lineage=_lineage(),
        usage_rights_status=UsageRightsStatus.PENDING,
        usage_rights_evidence_ref="rights/clip.json",
    )
    assert again.record_id == enriched.record_id
    assert again.lineage == _lineage()
    assert again.supersedes == enriched.supersedes
    assert len(read_records(proj, "asset_record")) == 2


def test_plain_reingest_after_enrichment_returns_active_enriched(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(proj, src)  # plain original
    enriched = ingest_asset(proj, src, lineage=_lineage(), usage_rights_status=UsageRightsStatus.PENDING)
    # A later *plain* re-ingest carries no metadata and must resolve to the active
    # enriched leaf, not the superseded plain original.
    plain_again = ingest_asset(proj, src)
    assert plain_again.record_id == enriched.record_id
    assert plain_again.lineage == _lineage()
    assert plain_again.usage_rights_status is UsageRightsStatus.PENDING
    assert len(read_records(proj, "asset_record")) == 2


def test_conflict_after_enrichment_fails_private(tmp_path):
    proj = open_project(tmp_path / "proj")
    src = _clip(tmp_path / "clip.mp4")
    ingest_asset(proj, src)  # plain original
    ingest_asset(proj, src, lineage=_lineage())  # enrich the plain original
    conflicting = GenerationLineage(generator_model="sora", provider_id="openai")
    # Conflicting metadata against the active enriched leaf is rejected privately,
    # and nothing is appended.
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src, lineage=conflicting)
    assert len(read_records(proj, "asset_record")) == 2


def test_ambiguous_active_records_fail_closed(tmp_path):
    proj = open_project(tmp_path / "proj")
    payload = b"\x00ambiguous-leaves\x01"
    src = _clip(tmp_path / "clip.mp4", payload)
    asset_id = "sha256:" + hashlib.sha256(payload).hexdigest()
    pid = proj.project_id
    # Plant two *active* (neither superseding the other) records for one asset_id.
    # Distinct original_locations give distinct canonical record ids.
    rec_a = AssetRecord(
        project_id=pid,
        created_by="tool",
        asset_id=asset_id,
        media_kind=MediaKind.VIDEO,
        original_location=str(asset_relative_path(asset_id, "clip.mp4")),
        byte_size=len(payload),
    )
    rec_b = AssetRecord(
        project_id=pid,
        created_by="tool",
        asset_id=asset_id,
        media_kind=MediaKind.VIDEO,
        original_location=str(asset_relative_path(asset_id, "other.mp4")),
        byte_size=len(payload),
    )
    append_record(proj, rec_a)
    append_record(proj, rec_b)
    # An ambiguous active set is not a base for enrichment or idempotency — the
    # duplicate lookup must fail closed with a stable, privacy-safe error.
    with pytest.raises(MCPVideoError):
        ingest_asset(proj, src)
