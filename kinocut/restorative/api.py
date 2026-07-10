"""Pure JSON-compatible adapters for restorative planning and evaluation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from .contracts import ModelRequirement, RestorativeCapability, RestorativeFeature, RestorativePlan
from .evaluators import PromotionEvaluation, evaluate_promotion
from .evidence import (
    AdvancedColorHDREvidence,
    BackgroundRepairEvidence,
    Evidence,
    FrameRepairEvidence,
    RestorativeEvidence,
    SpeechDenoiseEvidence,
    StyledCaptionEvidence,
)


class _PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    feature: RestorativeFeature
    source_sha256: str
    requested_executor_id: str
    model_requirement: ModelRequirement | None = None


_EVIDENCE_MODELS: dict[RestorativeFeature, type[RestorativeEvidence]] = {
    RestorativeFeature.SPEECH_DENOISE: SpeechDenoiseEvidence,
    RestorativeFeature.ADVANCED_COLOR_HDR: AdvancedColorHDREvidence,
    RestorativeFeature.FRAME_REPAIR: FrameRepairEvidence,
    RestorativeFeature.BACKGROUND_REPAIR: BackgroundRepairEvidence,
    RestorativeFeature.STYLED_CAPTIONS: StyledCaptionEvidence,
}
ModelT = TypeVar("ModelT", bound=BaseModel)


def plan_restoration(payload: Mapping[str, Any]) -> RestorativePlan:
    """Validate a JSON-compatible request and return a hash-bound local plan."""

    request = _PlanRequest.model_validate(dict(payload))
    return RestorativePlan.create(
        feature=request.feature,
        source_sha256=request.source_sha256,
        requested_executor_id=request.requested_executor_id,
        model_requirement=request.model_requirement,
    )


def _validated_model(value: ModelT | Mapping[str, Any], model: type[ModelT]) -> ModelT:
    return value if isinstance(value, model) else model.model_validate(dict(value))


def evaluate_restoration(
    *,
    plan: RestorativePlan | Mapping[str, Any],
    capability: RestorativeCapability | Mapping[str, Any],
    evidence: Evidence | Mapping[str, Any] | None,
) -> PromotionEvaluation:
    """Validate JSON-compatible artifacts and return a deterministic evaluation model."""

    validated_plan = _validated_model(plan, RestorativePlan)
    validated_capability = _validated_model(capability, RestorativeCapability)
    validated_evidence: Evidence | None
    if evidence is None:
        validated_evidence = None
    else:
        evidence_model = _EVIDENCE_MODELS[validated_plan.feature]
        validated_evidence = cast(Evidence, _validated_model(evidence, evidence_model))
    return evaluate_promotion(validated_plan, validated_capability, validated_evidence)
