"""Backward-reader fixtures for every existing receipt kind (Plan 00 Task 5).

Each legacy receipt kind — ``workflow``, ``workflow_batch``, ``rescue``,
``rescue_plan``, ``layer_plan`` — must (a) read as having *no* ``ai_video``
section without error, (b) still be parsed by the legacy-tolerant
``inspect_receipt``, and (c) accept an additive ``ai_video`` section without any
legacy top-level field changing and still parse afterwards.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from kinocut.engine_composite_layers import _build_layer_plan, _Canvas, _ResolvedLayer
from kinocut.receipts_ai_video import attach_ai_video_section, read_ai_video_section
from kinocut.rescue.models import (
    CleanupState,
    PackageManifest,
    RescueEstimate,
    RescuePlan,
    RescueReceipt,
    SourceIdentity,
)
from kinocut.workflow import inspect_receipt

_SHA = "sha256:" + "0" * 64
_SHA1 = "sha256:" + "1" * 64


def _source_identity() -> SourceIdentity:
    return SourceIdentity(path="input/broken.mp4", sha256=_SHA1, size_bytes=1, streams=[])


def _workflow_receipt() -> dict:
    # Producer-shaped: mirrors kinocut/workflow/executor.py:_render_one output,
    # with sources as a list of resolved entries carrying source hashes.
    return {
        "schema_version": 1,
        "receipt_kind": "workflow",
        "tool": "video_workflow_render",
        "versions": {"ffmpeg": "7.0", "kinocut": "0.1.0"},
        "spec_hash": _SHA,
        "workflow": {"name": "captioned", "variant": None},
        "sources": [
            {
                "id": "hero",
                "resolved": "input/hero.mp4",
                "source_hash": _SHA,
                "probe": {"duration": 1.0, "streams": ["video"]},
            }
        ],
        "steps": [
            {"id": "probe", "op": "probe", "status": "ok"},
            {"id": "trim", "op": "trim", "status": "ok", "output": "work/trim.mp4", "output_hash": _SHA},
        ],
        "outputs": [{"id": "master", "path": "output/final.mp4", "hash": _SHA}],
        "work_dir": "work/run-1",
        "cleanup_manifest": {"intermediates": [], "cleaned": [], "policy": "keep"},
        "resume_cursor": None,
        "feature_flags": {"variants": False, "resume_used": False, "resumed_from": None},
        "warnings": [],
        "status": "completed",
        "render_determinism_scope": "single_host",
    }


def _workflow_batch_receipt() -> dict:
    return {
        "schema_version": 1,
        "receipt_kind": "workflow_batch",
        "tool": "video_workflow_render",
        "versions": {"ffmpeg": "7.0"},
        "spec_hash": _SHA,
        "workflow": {"name": "captioned"},
        "status": "completed",
        "sources": [
            {
                "id": "hero",
                "resolved": "input/hero.mp4",
                "source_hash": _SHA,
                "probe": {"duration": 1.0, "streams": ["video"]},
            }
        ],
        "variants": [
            {
                "variant": "vertical",
                "status": "completed",
                "outputs": [{"id": "master", "path": "output/vertical.mp4", "hash": _SHA}],
            }
        ],
        "outputs": [{"id": "master", "path": "output/vertical.mp4", "hash": _SHA}],
        "warnings": [],
    }


def _rescue_receipt() -> dict:
    # Built from the real producer model so it validates against RescueReceipt.
    return RescueReceipt(
        status="quarantined",
        source=_source_identity(),
        plan_sha256=_SHA1,
        policy_sha256=_SHA1,
        package=PackageManifest(promoted=False),
        cleanup=CleanupState(work_dir="work"),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    ).model_dump(mode="json")


def _rescue_plan_receipt() -> dict:
    # Built from the real producer model so it validates against RescuePlan.
    return RescuePlan(
        workspace_root=".",
        output_root="rescue-output",
        source=_source_identity(),
        estimate=RescueEstimate(seconds=0.0, hardware={}, confidence="high"),
        capabilities={"local_only": True},
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        observed_planning_seconds=0.0,
    ).model_dump(mode="json")


def _layer_plan_receipt() -> dict:
    # Built by the real producer (_build_layer_plan) so it is exactly the v2
    # output and cannot drift. A solid layer needs no source file.
    canvas = _Canvas(width=1920, height=1080, fps=30.0, duration=5.0)
    layer = _ResolvedLayer(
        id="bg", type="solid", opacity=1.0, position={"x": 0.0, "y": 0.0}, color="#000000", input_index=0
    )
    return _build_layer_plan(
        b'{"canvas":{"width":1920}}', canvas, [layer], "color=c=black[bg]", "output/final.mp4", Path(".")
    )


_RECEIPTS = {
    "workflow": _workflow_receipt,
    "workflow_batch": _workflow_batch_receipt,
    "rescue": _rescue_receipt,
    "rescue_plan": _rescue_plan_receipt,
    "layer_plan": _layer_plan_receipt,
}

_SECTION = {
    "contract_version": 1,
    "project_id": "proj",
    "acceptance_spec_id": None,
    "ordered_inputs": [],
    "transformations": [],
    "duration_policy": "preserve",
    "preservation_proofs": [],
    "finding_ids": [],
    "review_artifact_ids": [],
    "approval_state_id": None,
    "warnings": [],
}


@pytest.mark.parametrize("kind", sorted(_RECEIPTS))
def test_legacy_receipt_has_no_ai_video_section(kind):
    assert read_ai_video_section(_RECEIPTS[kind]()) is None


# Expected normalized (kind, status.overall) that inspect_receipt must report.
_EXPECTED = {
    "workflow": ("workflow", "completed"),
    "workflow_batch": ("workflow_batch", "completed"),
    "rescue": ("rescue", "quarantined"),
    "rescue_plan": ("rescue_plan", "planned"),
    "layer_plan": ("layer_plan", "planned"),
}


def test_rescue_fixtures_validate_against_producer_models():
    # The rescue fixtures are produced by the real models, so they round-trip.
    RescueReceipt.model_validate(_rescue_receipt())
    RescuePlan.model_validate(_rescue_plan_receipt())


# Exact producer v2 top-level keys — a drift guard against a hand-shaped fixture.
_LAYER_PLAN_V2_KEYS = {
    "schema_version",
    "receipt_kind",
    "tool",
    "spec_hash",
    "canvas",
    "layers",
    "filtergraph_summary",
    "filtergraph_hash",
    "output_path",
    "output_hash",
    "audio_policy",
    "features",
    "render_determinism_scope",
}
_LAYER_V2_LAYER_KEYS = {
    "id",
    "type",
    "resolved_src",
    "source_hash",
    "opacity",
    "position",
    "transform",
    "timing",
    "mask",
    "mask_hash",
    "blend",
    "color",
    "input_index",
    "mask_input_index",
}


def test_layer_plan_fixture_is_exact_producer_v2():
    plan = _layer_plan_receipt()
    assert plan["schema_version"] == 2  # v2, not a hand-minimal v1
    assert set(plan) == _LAYER_PLAN_V2_KEYS  # drift guard: exact producer key set
    assert set(plan["layers"][0]) == _LAYER_V2_LAYER_KEYS


def test_workflow_sources_are_producer_list_shape():
    for build in (_workflow_receipt, _workflow_batch_receipt):
        sources = build()["sources"]
        assert isinstance(sources, list) and sources
        assert {"id", "resolved", "source_hash", "probe"}.issubset(sources[0])


@pytest.mark.parametrize("kind", sorted(_RECEIPTS))
def test_inspect_receipt_normalizes_legacy_kind(tmp_path, kind):
    path = tmp_path / f"{kind}.json"
    path.write_text(json.dumps(_RECEIPTS[kind]()), encoding="utf-8")
    result = inspect_receipt(str(path))  # must not raise
    expected_kind, expected_status = _EXPECTED[kind]
    assert result["kind"] == expected_kind
    assert result["status"]["overall"] == expected_status
    # The normalized shape carries the meaningful review/integrity keys.
    assert {"integrity", "human_review", "outputs"}.issubset(result)


@pytest.mark.parametrize("kind", sorted(_RECEIPTS))
def test_additive_section_preserves_legacy_fields_and_parses(tmp_path, kind):
    from kinocut.contracts.receipt_ai_video import AiVideoReceiptSection

    legacy = _RECEIPTS[kind]()
    merged = attach_ai_video_section(legacy, AiVideoReceiptSection(**_SECTION))
    # Every legacy top-level field survives unchanged.
    for key, value in legacy.items():
        assert merged[key] == value
    assert "ai_video" in merged
    path = tmp_path / f"{kind}_ai.json"
    path.write_text(json.dumps(merged), encoding="utf-8")
    assert isinstance(inspect_receipt(str(path)), dict)  # still parses with the section
    assert read_ai_video_section(merged) is not None


def test_backward_reader_fixtures_carry_no_home_paths():
    home = str(Path.home())
    for build in _RECEIPTS.values():
        assert home not in json.dumps(build())
