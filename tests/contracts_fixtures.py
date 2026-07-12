"""Canonical valid/invalid record builders for AI-video contract tests.

Builders return **primitive** kwargs only (str/int/float/tuple/dict) and never
import the domain contract modules. Pydantic coerces nested dicts into embedded
value objects and strings into ``StrEnum`` members at construction time, so the
already-green ``test_contracts_common`` suite keeps importing this module even
before the Task 2 domain models exist.
"""

from __future__ import annotations

from typing import Any

# Canonical sha256-shaped constants reused across record builders.
_SHA = "sha256:" + "a" * 64
_SHA_B = "sha256:" + "b" * 64
_ASSET = "sha256:" + "c" * 64


def valid_record_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return a minimal set of valid ``RecordBase`` keyword arguments.

    ``created_at`` is intentionally omitted so callers can vary it while
    asserting it does not participate in the canonical record id.
    """

    kwargs: dict[str, Any] = {
        "schema_version": 1,
        "record_kind": "sample_record",
        "project_id": "proj-alpha",
        "created_by": "human",
    }
    kwargs.update(overrides)
    return kwargs


def invalid_record_kwargs(**overrides: Any) -> dict[str, Any]:
    """Return record kwargs carrying an unknown field that must fail validation."""

    kwargs = valid_record_kwargs()
    kwargs["surprise"] = True
    kwargs.update(overrides)
    return kwargs


def _base(created_by: str = "human", **overrides: Any) -> dict[str, Any]:
    """Return the shared provenance kwargs every domain record needs.

    ``schema_version`` and ``record_kind`` are intentionally omitted: each
    domain model defaults them, so builders only supply provenance and the
    model-specific semantic fields.
    """

    kwargs: dict[str, Any] = {"project_id": "proj-alpha", "created_by": created_by}
    kwargs.update(overrides)
    return kwargs


def acceptance_spec_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``GenerationAcceptanceSpec`` (design §4.2)."""

    kwargs = _base(
        spec_id="spec-1",
        title="Hero shot",
        target_formats=("mp4", "mov"),
        review_policy="dual_control",
        required_subjects=("mascot",),
        required_actions=("wave",),
        semantic_beats=("intro", "cta"),
        exact_text_hash=_SHA,
        declared_text_region={"x": 0.1, "y": 0.1, "width": 0.2, "height": 0.05},
        required_logos=("brand",),
        visual_rules=("no_text_warp",),
        forbidden_defect_codes=("text_drift",),
        severity_thresholds=({"defect_code": "identity_drift", "max_severity": "low"},),
        required_evidence_artifacts=("motion_strip",),
        required_review_roles=("editor",),
        continuity_plan_ref=None,
        cost_ceiling=None,
    )
    kwargs.update(overrides)
    return kwargs


def generation_lineage_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for an embedded ``GenerationLineage`` value object (design §4.3)."""

    kwargs: dict[str, Any] = {
        "generator_model": "veo-3",
        "provider_id": "provider-x",
        "prompt_hash": _SHA,
        "generation_settings_hash": _SHA_B,
        "source_asset_ids": (_ASSET,),
        "reference_asset_ids": (),
    }
    kwargs.update(overrides)
    return kwargs


def asset_record_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``AssetRecord`` (design §4.3)."""

    kwargs = _base(
        created_by="tool",
        asset_id=_ASSET,
        media_kind="video",
        original_location="inputs/clip01.mp4",
        byte_size=1234,
        ingest_time="2026-01-01T00:00:00Z",
        preflight_summary="ok",
        preflight_artifact_id=_SHA,
        usage_rights_status="cleared",
        usage_rights_evidence_ref="rights/clip01.json",
        lineage=None,
        parent_asset_id=None,
        variant_of=None,
        derived_artifact_ids=(),
    )
    kwargs.update(overrides)
    return kwargs


def verdict_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``ClipVerdict`` (design §4.4)."""

    kwargs = _base(
        asset_hash=_ASSET,
        disposition="approved",
        approved_range=None,
        acceptance_spec_id=_SHA,
        reviewer="editor",
        rationale="meets acceptance spec",
        defect_ids=(),
        review_decision_id=None,
    )
    kwargs.update(overrides)
    return kwargs


def defect_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``DefectFinding`` (design §4.5)."""

    kwargs = _base(
        created_by="agent",
        defect_code="text_drift",
        target_id=_ASSET,
        time_range=(0.0, 1.5),
        spatial_region=None,
        severity="medium",
        confidence=0.8,
        detector="deterministic:text_probe",
        measurements=({"name": "drift_px", "value": 12.0, "unit": "px"},),
        evidence_artifact_ids=(_SHA,),
        status="suspected",
        human_decision_id=None,
    )
    kwargs.update(overrides)
    return kwargs


def protection_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``ProtectedElement`` (design §4.6)."""

    kwargs = _base(
        element_type="audio_stream",
        dependency_fingerprint=_SHA,
        allowed_operations=("loudness_normalize",),
        duration_policy="preserve",
        human_approval_ref=_SHA,
    )
    kwargs.update(overrides)
    return kwargs


def review_decision_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``ReviewDecision`` (design §4.9)."""

    kwargs = _base(
        actor="human",
        decision="approve",
        target_ref=_ASSET,
        target_range=None,
        rationale="approved after review",
        dependency_fingerprint=_SHA,
    )
    kwargs.update(overrides)
    return kwargs


def known_limitation_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``KnownLimitation`` (design §4.9)."""

    kwargs = _base(
        summary="minor flicker in final frame",
        related_defect_ids=(_SHA,),
        accepted_by_decision_id=_SHA_B,
    )
    kwargs.update(overrides)
    return kwargs


def approval_state_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``ApprovalState`` (design §4.9)."""

    kwargs = _base(
        candidate_artifact=_SHA,
        dependency_fingerprint=_SHA_B,
        required_artifact_ids=(_SHA,),
        integrity_results=({"artifact_id": _SHA, "passed": True},),
        required_human_decisions=(_ASSET,),
        state="pending",
        invalidation_reasons=(),
        superseding_state_id=None,
    )
    kwargs.update(overrides)
    return kwargs


def prompt_outcome_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``PromptOutcome`` (design §4.11)."""

    kwargs = _base(
        created_by="agent",
        prompt_hash=_SHA,
        generator_model="veo-3",
        generator_settings_hash=_SHA_B,
        asset_ids=(_ASSET,),
        verdict_ids=(_SHA,),
        defect_ids=(),
        final_use_event_ids=(),
    )
    kwargs.update(overrides)
    return kwargs


def usage_event_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``UsageEvent`` (design §4.11)."""

    kwargs = _base(
        created_by="tool",
        asset_id=_ASSET,
        project_beat="intro",
        output_receipt_id=_SHA,
        timestamp="2026-01-01T00:00:00Z",
    )
    kwargs.update(overrides)
    return kwargs


def cost_event_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``CostEvent`` (design §4.11).

    Defaults to a known cost; ``amount`` may be overridden to ``None`` with
    ``confidence="unknown"`` to exercise the explicit-unknown-cost invariant.
    """

    kwargs = _base(
        created_by="tool",
        category="generation",
        quantity=1.0,
        unit="clip",
        currency="USD",
        source="provider_invoice",
        amount=1.25,
        confidence="known",
    )
    kwargs.update(overrides)
    return kwargs


def workflow_recipe_kwargs(**overrides: Any) -> dict[str, Any]:
    """Kwargs for a valid ``WorkflowRecipe`` (design §4.11)."""

    kwargs = _base(
        recipe_version=1,
        template="hero_shot_v1",
        parameter_slots=({"name": "subject", "type": "string", "required": True},),
        policies=("preserve_audio",),
        required_checks=("black_frame",),
        review_gates=("editor_signoff",),
    )
    kwargs.update(overrides)
    return kwargs
