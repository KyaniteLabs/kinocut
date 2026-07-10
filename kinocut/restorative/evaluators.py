"""Deterministic, side-effect-free restorative promotion evaluators."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .contracts import (
    CapabilityStatus,
    ModelProvenance,
    ModelRequirement,
    RestorativeCapability,
    RestorativeFeature,
    RestorativePlan,
    VERIFICATION_CONTRACTS,
    _FrozenModel,
    plan_digest,
)
from .evidence import (
    AdvancedColorHDREvidence,
    BackgroundRepairEvidence,
    Evidence,
    FrameRepairEvidence,
    RestorativeEvidence,
    SpeechDenoiseEvidence,
    StyledCaptionEvidence,
)


class PromotionDecision(StrEnum):
    PROMOTE = "promote"
    REJECT = "reject"
    ABSTAIN = "abstain"


class GateResult(_FrozenModel):
    id: str = Field(min_length=1)
    passed: bool
    observed: bool | int | float | str
    requirement: str = Field(min_length=1)


class PromotionEvaluation(_FrozenModel):
    schema_version: int = 1
    feature: RestorativeFeature
    decision: PromotionDecision
    promotable: bool
    plan_sha256: str
    verification_contract_id: str
    gates: tuple[GateResult, ...] = ()
    reason_codes: tuple[str, ...] = ()
    model_provenance: ModelProvenance | None = None

    @model_validator(mode="after")
    def decision_matches_receipt(self) -> PromotionEvaluation:
        if self.promotable is not (self.decision is PromotionDecision.PROMOTE):
            raise ValueError("promotable must exactly match the promote decision")
        if self.decision is PromotionDecision.PROMOTE and (
            not self.gates or self.reason_codes or not all(gate.passed for gate in self.gates)
        ):
            raise ValueError("promotion requires all gates and no reason codes")
        if self.decision is PromotionDecision.REJECT and not self.reason_codes:
            raise ValueError("rejection requires failed gate reason codes")
        if self.decision is PromotionDecision.ABSTAIN and (self.gates or not self.reason_codes):
            raise ValueError("abstention requires reasons and no feature gate claims")
        return self


def _gate(gate_id: str, passed: bool, observed: bool | int | float | str, requirement: str) -> GateResult:
    return GateResult(id=gate_id, passed=passed, observed=observed, requirement=requirement)


def _model_matches(requirement: ModelRequirement, provenance: ModelProvenance | None) -> bool:
    return provenance is not None and (
        provenance.model_id,
        provenance.version,
        provenance.sha256,
    ) == (requirement.model_id, requirement.version, requirement.sha256)


def _abstain(plan: RestorativePlan, reason: str) -> PromotionEvaluation:
    return PromotionEvaluation(
        feature=plan.feature,
        decision=PromotionDecision.ABSTAIN,
        promotable=False,
        plan_sha256=plan.plan_sha256,
        verification_contract_id=plan.verification_contract_id,
        reason_codes=(reason,),
    )


def _finish(plan: RestorativePlan, evidence: RestorativeEvidence, gates: tuple[GateResult, ...]) -> PromotionEvaluation:
    failed = tuple(gate.id for gate in gates if not gate.passed)
    decision = PromotionDecision.REJECT if failed else PromotionDecision.PROMOTE
    return PromotionEvaluation(
        feature=plan.feature,
        decision=decision,
        promotable=not failed,
        plan_sha256=plan.plan_sha256,
        verification_contract_id=plan.verification_contract_id,
        gates=gates,
        reason_codes=failed,
        model_provenance=evidence.model_provenance,
    )


def evaluate_speech_denoise(evidence: SpeechDenoiseEvidence) -> tuple[GateResult, ...]:
    noise_reduction = evidence.noise_before_dbfs - evidence.noise_after_dbfs
    return (
        _gate("noise_reduced", noise_reduction >= 1.0, noise_reduction, ">= 1.0 dB reduction"),
        _gate(
            "snr_non_regression",
            evidence.snr_after_db >= evidence.snr_before_db,
            evidence.snr_after_db - evidence.snr_before_db,
            ">= 0.0 dB change",
        ),
        _gate(
            "intelligibility_preserved",
            evidence.intelligibility_after >= evidence.intelligibility_before,
            evidence.intelligibility_after - evidence.intelligibility_before,
            ">= 0.0 change",
        ),
        _gate(
            "speech_coverage_preserved",
            evidence.speech_coverage_after >= evidence.speech_coverage_before,
            evidence.speech_coverage_after - evidence.speech_coverage_before,
            ">= 0.0 change",
        ),
    )


def evaluate_advanced_color_hdr(evidence: AdvancedColorHDREvidence) -> tuple[GateResult, ...]:
    clipping_stable = evidence.clipping_after_fraction <= 0.01 and (
        evidence.clipping_after_fraction <= evidence.clipping_before_fraction + 0.001
    )
    return (
        _gate("calibrated_measurement", evidence.calibrated, evidence.calibrated, "calibrated evidence required"),
        _gate(
            "delivery_color_space",
            evidence.output_color_space == evidence.delivery_color_space,
            evidence.output_color_space,
            f"equals {evidence.delivery_color_space}",
        ),
        _gate(
            "gamut_within_delivery",
            evidence.out_of_gamut_fraction <= 0.001,
            evidence.out_of_gamut_fraction,
            "<= 0.001 fraction",
        ),
        _gate("clipping_stable", clipping_stable, evidence.clipping_after_fraction, "<= 0.01 and increase <= 0.001"),
        _gate("neutral_stability", evidence.neutral_delta_e <= 3.0, evidence.neutral_delta_e, "delta E <= 3.0"),
        _gate("skin_stability", evidence.skin_delta_e <= 4.0, evidence.skin_delta_e, "delta E <= 4.0"),
    )


def evaluate_frame_repair(evidence: FrameRepairEvidence) -> tuple[GateResult, ...]:
    return (
        _gate(
            "temporal_consistency",
            evidence.temporal_consistency_score >= 0.95,
            evidence.temporal_consistency_score,
            ">= 0.95",
        ),
        _gate(
            "identity_continuity",
            evidence.identity_continuity_score >= 0.99,
            evidence.identity_continuity_score,
            ">= 0.99",
        ),
        _gate(
            "object_continuity",
            evidence.object_continuity_score >= 0.99,
            evidence.object_continuity_score,
            ">= 0.99",
        ),
        _gate(
            "source_detail_coverage",
            evidence.source_detail_coverage == 1.0,
            evidence.source_detail_coverage,
            "equals 1.0",
        ),
        _gate(
            "no_invented_detail",
            not evidence.invented_detail_detected,
            evidence.invented_detail_detected,
            "false",
        ),
        _gate(
            "no_invented_detail_claim",
            not evidence.invented_detail_claimed,
            evidence.invented_detail_claimed,
            "false",
        ),
    )


def evaluate_background_repair(evidence: BackgroundRepairEvidence) -> tuple[GateResult, ...]:
    return (
        _gate(
            "segmentation_confidence",
            evidence.segmentation_confidence >= 0.95,
            evidence.segmentation_confidence,
            ">= 0.95",
        ),
        _gate(
            "foreground_coverage_preserved",
            evidence.foreground_coverage_after >= evidence.foreground_coverage_before,
            evidence.foreground_coverage_after - evidence.foreground_coverage_before,
            ">= 0.0 change",
        ),
        _gate(
            "foreground_object_coverage",
            evidence.foreground_object_coverage >= 0.99,
            evidence.foreground_object_coverage,
            ">= 0.99",
        ),
        _gate(
            "edge_stability",
            evidence.edge_temporal_stability >= 0.95,
            evidence.edge_temporal_stability,
            ">= 0.95",
        ),
        _gate(
            "no_invented_background",
            not evidence.invented_background,
            evidence.invented_background,
            "false",
        ),
    )


def evaluate_styled_captions(evidence: StyledCaptionEvidence) -> tuple[GateResult, ...]:
    return (
        _gate("style_approved", evidence.style_approved, evidence.style_approved, "true"),
        _gate(
            "readable_contrast",
            evidence.minimum_contrast_ratio >= 4.5,
            evidence.minimum_contrast_ratio,
            ">= 4.5:1",
        ),
        _gate(
            "no_caption_clipping",
            evidence.clipped_caption_count == 0,
            evidence.clipped_caption_count,
            "equals 0",
        ),
        _gate("safe_zone_coverage", evidence.safe_zone_coverage == 1.0, evidence.safe_zone_coverage, "equals 1.0"),
        _gate("timing_valid", evidence.timing_valid, evidence.timing_valid, "true"),
        _gate(
            "timing_stable",
            evidence.maximum_timing_drift_ms <= 50,
            evidence.maximum_timing_drift_ms,
            "<= 50 ms",
        ),
    )


_EXPECTED_EVIDENCE: dict[RestorativeFeature, type[RestorativeEvidence]] = {
    RestorativeFeature.SPEECH_DENOISE: SpeechDenoiseEvidence,
    RestorativeFeature.ADVANCED_COLOR_HDR: AdvancedColorHDREvidence,
    RestorativeFeature.FRAME_REPAIR: FrameRepairEvidence,
    RestorativeFeature.BACKGROUND_REPAIR: BackgroundRepairEvidence,
    RestorativeFeature.STYLED_CAPTIONS: StyledCaptionEvidence,
}
_EVALUATORS: dict[RestorativeFeature, Callable[[Any], tuple[GateResult, ...]]] = {
    RestorativeFeature.SPEECH_DENOISE: evaluate_speech_denoise,
    RestorativeFeature.ADVANCED_COLOR_HDR: evaluate_advanced_color_hdr,
    RestorativeFeature.FRAME_REPAIR: evaluate_frame_repair,
    RestorativeFeature.BACKGROUND_REPAIR: evaluate_background_repair,
    RestorativeFeature.STYLED_CAPTIONS: evaluate_styled_captions,
}


def evaluate_promotion(
    plan: RestorativePlan,
    capability: RestorativeCapability,
    evidence: Evidence | None,
) -> PromotionEvaluation:
    """Evaluate one feature without I/O, substitution, or implicit capability discovery."""

    if plan.plan_sha256 != plan_digest(plan):
        return _abstain(plan, "plan_digest_mismatch")
    if capability.feature is not plan.feature:
        return _abstain(plan, "capability_feature_mismatch")
    if capability.status is not CapabilityStatus.AVAILABLE:
        return _abstain(plan, f"capability_{capability.status.value}")
    if capability.executor_id != plan.requested_executor_id:
        return _abstain(plan, "executor_mismatch")
    if evidence is None:
        return _abstain(plan, "evidence_unavailable")
    if not isinstance(evidence, _EXPECTED_EVIDENCE[plan.feature]):
        return _abstain(plan, "evidence_feature_mismatch")
    if evidence.plan_sha256 != plan.plan_sha256:
        return _abstain(plan, "evidence_plan_mismatch")

    if plan.model_requirement is not None:
        if not _model_matches(plan.model_requirement, capability.model_provenance):
            return _abstain(plan, "model_provenance_mismatch")
        if not _model_matches(plan.model_requirement, evidence.model_provenance):
            return _abstain(plan, "model_provenance_mismatch")
        if capability.model_provenance != evidence.model_provenance:
            return _abstain(plan, "model_provenance_mismatch")
    elif capability.model_provenance is not None or evidence.model_provenance is not None:
        return _abstain(plan, "unplanned_model")

    gates = _EVALUATORS[plan.feature](evidence)
    contract = VERIFICATION_CONTRACTS[plan.feature]
    if tuple(gate.id for gate in gates) != contract.required_gate_ids:
        return _abstain(plan, "verification_contract_mismatch")
    return _finish(plan, evidence, gates)
