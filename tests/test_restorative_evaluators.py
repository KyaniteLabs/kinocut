from __future__ import annotations

import pytest

from mcp_video.restorative import (
    AdvancedColorHDREvidence,
    BackgroundRepairEvidence,
    CapabilityStatus,
    FrameRepairEvidence,
    ModelProvenance,
    ModelRequirement,
    NoiseType,
    PromotionDecision,
    RestorativeCapability,
    RestorativeFeature,
    RestorativePlan,
    SpeechDenoiseEvidence,
    StyledCaptionEvidence,
    evaluate_restoration,
    evaluate_promotion,
    plan_restoration,
)


SHA_A = "sha256:" + "a" * 64
SHA_B = "sha256:" + "b" * 64
SHA_C = "sha256:" + "c" * 64


def _model(*, sha256: str = SHA_B) -> ModelProvenance:
    return ModelProvenance(
        model_id="local.repair",
        version="1.0",
        sha256=sha256,
        origin="bundled",
        loaded_from="models/repair.bin",
        determinism_scope="same model, executor, hardware, and inputs",
    )


def _plan(feature: RestorativeFeature) -> RestorativePlan:
    model_requirement = None
    if feature is RestorativeFeature.FRAME_REPAIR:
        model_requirement = ModelRequirement(model_id="local.repair", version="1.0", sha256=SHA_B)
    return RestorativePlan.create(
        feature=feature,
        source_sha256=SHA_A,
        requested_executor_id=f"local.{feature.value}",
        model_requirement=model_requirement,
    )


def _capability(plan: RestorativePlan) -> RestorativeCapability:
    return RestorativeCapability(
        feature=plan.feature,
        status=CapabilityStatus.AVAILABLE,
        executor_id=plan.requested_executor_id,
        executor_version="1.0",
        model_provenance=_model() if plan.model_requirement else None,
    )


def _speech(plan: RestorativePlan, **updates: object) -> SpeechDenoiseEvidence:
    values = {
        "plan_sha256": plan.plan_sha256,
        "output_sha256": SHA_C,
        "sample_count": 24,
        "noise_type": NoiseType.WIND,
        "noise_before_dbfs": -38.0,
        "noise_after_dbfs": -44.0,
        "snr_before_db": 12.0,
        "snr_after_db": 17.0,
        "intelligibility_before": 0.84,
        "intelligibility_after": 0.88,
        "speech_coverage_before": 0.92,
        "speech_coverage_after": 0.92,
    }
    values.update(updates)
    return SpeechDenoiseEvidence(**values)


def _color(plan: RestorativePlan, **updates: object) -> AdvancedColorHDREvidence:
    values = {
        "plan_sha256": plan.plan_sha256,
        "output_sha256": SHA_C,
        "sample_count": 24,
        "calibrated": True,
        "calibration_profile": "chart-d65-v1",
        "input_color_space": "bt709",
        "output_color_space": "bt2020-pq",
        "delivery_color_space": "bt2020-pq",
        "out_of_gamut_fraction": 0.0005,
        "clipping_before_fraction": 0.004,
        "clipping_after_fraction": 0.0045,
        "neutral_delta_e": 1.4,
        "neutral_sample_count": 12,
        "skin_delta_e": 2.1,
        "skin_sample_count": 8,
    }
    values.update(updates)
    return AdvancedColorHDREvidence(**values)


def _frame(plan: RestorativePlan, **updates: object) -> FrameRepairEvidence:
    values = {
        "plan_sha256": plan.plan_sha256,
        "output_sha256": SHA_C,
        "sample_count": 24,
        "model_provenance": _model(),
        "repair_kind": "upscale",
        "temporal_consistency_score": 0.97,
        "identity_continuity_score": 0.995,
        "object_continuity_score": 0.995,
        "source_detail_coverage": 1.0,
        "invented_detail_detected": False,
        "invented_detail_claimed": False,
    }
    values.update(updates)
    return FrameRepairEvidence(**values)


def _background(plan: RestorativePlan, **updates: object) -> BackgroundRepairEvidence:
    values = {
        "plan_sha256": plan.plan_sha256,
        "output_sha256": SHA_C,
        "sample_count": 24,
        "segmentation_confidence": 0.98,
        "foreground_coverage_before": 0.96,
        "foreground_coverage_after": 0.96,
        "foreground_object_coverage": 0.995,
        "edge_temporal_stability": 0.97,
        "invented_background": False,
    }
    values.update(updates)
    return BackgroundRepairEvidence(**values)


def _captions(plan: RestorativePlan, **updates: object) -> StyledCaptionEvidence:
    values = {
        "plan_sha256": plan.plan_sha256,
        "output_sha256": SHA_C,
        "sample_count": 24,
        "style_approved": True,
        "minimum_contrast_ratio": 7.1,
        "clipped_caption_count": 0,
        "safe_zone_coverage": 1.0,
        "timing_valid": True,
        "maximum_timing_drift_ms": 20,
    }
    values.update(updates)
    return StyledCaptionEvidence(**values)


@pytest.mark.parametrize(
    ("feature", "evidence_factory", "expected_gates"),
    [
        (
            RestorativeFeature.SPEECH_DENOISE,
            _speech,
            ("noise_reduced", "snr_non_regression", "intelligibility_preserved", "speech_coverage_preserved"),
        ),
        (
            RestorativeFeature.ADVANCED_COLOR_HDR,
            _color,
            (
                "calibrated_measurement",
                "delivery_color_space",
                "gamut_within_delivery",
                "clipping_stable",
                "neutral_stability",
                "skin_stability",
            ),
        ),
        (
            RestorativeFeature.FRAME_REPAIR,
            _frame,
            (
                "temporal_consistency",
                "identity_continuity",
                "object_continuity",
                "source_detail_coverage",
                "no_invented_detail",
                "no_invented_detail_claim",
            ),
        ),
        (
            RestorativeFeature.BACKGROUND_REPAIR,
            _background,
            (
                "segmentation_confidence",
                "foreground_coverage_preserved",
                "foreground_object_coverage",
                "edge_stability",
                "no_invented_background",
            ),
        ),
        (
            RestorativeFeature.STYLED_CAPTIONS,
            _captions,
            (
                "style_approved",
                "readable_contrast",
                "no_caption_clipping",
                "safe_zone_coverage",
                "timing_valid",
                "timing_stable",
            ),
        ),
    ],
)
def test_feature_promotes_only_after_its_ordered_gates_pass(feature, evidence_factory, expected_gates) -> None:
    plan = _plan(feature)
    evidence = evidence_factory(plan)

    first = evaluate_promotion(plan, _capability(plan), evidence)
    second = evaluate_promotion(plan, _capability(plan), evidence)

    assert first == second
    assert first.decision is PromotionDecision.PROMOTE
    assert first.promotable is True
    assert tuple(gate.id for gate in first.gates) == expected_gates
    assert all(gate.passed for gate in first.gates)


@pytest.mark.parametrize(
    ("feature", "evidence_factory", "updates", "failed_gate"),
    [
        (RestorativeFeature.SPEECH_DENOISE, _speech, {"intelligibility_after": 0.70}, "intelligibility_preserved"),
        (RestorativeFeature.ADVANCED_COLOR_HDR, _color, {"skin_delta_e": 7.0}, "skin_stability"),
        (RestorativeFeature.FRAME_REPAIR, _frame, {"invented_detail_claimed": True}, "no_invented_detail_claim"),
        (
            RestorativeFeature.BACKGROUND_REPAIR,
            _background,
            {"foreground_coverage_after": 0.80},
            "foreground_coverage_preserved",
        ),
        (RestorativeFeature.STYLED_CAPTIONS, _captions, {"clipped_caption_count": 1}, "no_caption_clipping"),
    ],
)
def test_feature_gate_failure_rejects_promotion(feature, evidence_factory, updates, failed_gate) -> None:
    plan = _plan(feature)

    result = evaluate_promotion(plan, _capability(plan), evidence_factory(plan, **updates))

    assert result.decision is PromotionDecision.REJECT
    assert result.promotable is False
    assert failed_gate in result.reason_codes


@pytest.mark.parametrize("status", [CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNSUPPORTED])
def test_non_available_capability_abstains_without_evidence_or_substitution(status: CapabilityStatus) -> None:
    plan = _plan(RestorativeFeature.SPEECH_DENOISE)
    capability = RestorativeCapability(feature=plan.feature, status=status, reason="backend absent")

    result = evaluate_promotion(plan, capability, None)

    assert result.decision is PromotionDecision.ABSTAIN
    assert result.promotable is False
    assert result.gates == ()
    assert result.reason_codes == (f"capability_{status.value}",)


def test_missing_evidence_abstains() -> None:
    plan = _plan(RestorativeFeature.STYLED_CAPTIONS)

    result = evaluate_promotion(plan, _capability(plan), None)

    assert result.decision is PromotionDecision.ABSTAIN
    assert result.reason_codes == ("evidence_unavailable",)


def test_evidence_bound_to_another_plan_abstains() -> None:
    plan = _plan(RestorativeFeature.SPEECH_DENOISE)

    result = evaluate_promotion(plan, _capability(plan), _speech(plan, plan_sha256=SHA_B))

    assert result.decision is PromotionDecision.ABSTAIN
    assert result.reason_codes == ("evidence_plan_mismatch",)


def test_model_mismatch_abstains_instead_of_substituting() -> None:
    plan = _plan(RestorativeFeature.FRAME_REPAIR)
    mismatched_capability = _capability(plan).model_copy(update={"model_provenance": _model(sha256=SHA_C)})

    result = evaluate_promotion(plan, mismatched_capability, _frame(plan))

    assert result.decision is PromotionDecision.ABSTAIN
    assert result.reason_codes == ("model_provenance_mismatch",)


def test_public_plan_api_accepts_json_compatible_values() -> None:
    plan = plan_restoration(
        {
            "feature": "styled_captions",
            "source_sha256": SHA_A,
            "requested_executor_id": "local.styled_captions",
        }
    )

    assert isinstance(plan, RestorativePlan)
    assert plan.feature is RestorativeFeature.STYLED_CAPTIONS


def test_public_evaluate_api_validates_json_compatible_evidence() -> None:
    plan = plan_restoration(
        {
            "feature": "styled_captions",
            "source_sha256": SHA_A,
            "requested_executor_id": "local.styled_captions",
        }
    )
    result = evaluate_restoration(
        plan=plan.model_dump(mode="json"),
        capability={
            "feature": "styled_captions",
            "status": "available",
            "executor_id": "local.styled_captions",
            "executor_version": "1.0",
        },
        evidence={
            "plan_sha256": plan.plan_sha256,
            "output_sha256": SHA_C,
            "sample_count": 24,
            "style_approved": True,
            "minimum_contrast_ratio": 7.1,
            "clipped_caption_count": 0,
            "safe_zone_coverage": 1.0,
            "timing_valid": True,
            "maximum_timing_drift_ms": 20,
        },
    )

    assert result.decision is PromotionDecision.PROMOTE
    assert result.model_dump(mode="json")["promotable"] is True
