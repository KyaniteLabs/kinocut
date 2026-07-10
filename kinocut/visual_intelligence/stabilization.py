"""Pure V3 stabilization planning with conservative abstention."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from kinocut.errors import ValidationError

from .models import (
    CropBudget,
    NormalizedBox,
    StabilizationPlan,
    StabilizationTransform,
    VisualAnalysisPlan,
    canonical_sha256,
)


def _coverage(content: NormalizedBox, window: NormalizedBox) -> float:
    left = max(content.x, window.x)
    top = max(content.y, window.y)
    right = min(content.x + content.width, window.x + window.width)
    bottom = min(content.y + content.height, window.y + window.height)
    intersection = max(0.0, right - left) * max(0.0, bottom - top)
    return max(0.0, min(1.0, intersection / content.area))


def _transforms(analysis: VisualAnalysisPlan, ratio: float) -> tuple[StabilizationTransform, ...]:
    return tuple(
        StabilizationTransform(
            timestamp_seconds=motion.timestamp_seconds,
            translate_x=-motion.dx * ratio,
            translate_y=-motion.dy * ratio,
            rotation_degrees=-motion.rotation_degrees * ratio,
            zoom_delta=-motion.zoom_delta * ratio,
        )
        for motion in analysis.camera_motion
    )


def _required_crop(transforms: tuple[StabilizationTransform, ...]) -> NormalizedBox | None:
    rotation_margin = max((abs(item.rotation_degrees) / 180.0 for item in transforms), default=0.0)
    zoom_out_margin = max((max(0.0, -item.zoom_delta) / 2.0 for item in transforms), default=0.0)
    margin_x = max((abs(item.translate_x) for item in transforms), default=0.0) + rotation_margin + zoom_out_margin
    margin_y = max((abs(item.translate_y) for item in transforms), default=0.0) + rotation_margin + zoom_out_margin
    if margin_x >= 0.5 or margin_y >= 0.5:
        return None
    return NormalizedBox(x=margin_x, y=margin_y, width=1.0 - 2.0 * margin_x, height=1.0 - 2.0 * margin_y)


def _motion_score(analysis: VisualAnalysisPlan) -> float:
    magnitudes = [
        math.sqrt(motion.dx**2 + motion.dy**2 + (motion.rotation_degrees / 180.0) ** 2 + motion.zoom_delta**2)
        for motion in analysis.camera_motion
    ]
    return sum(magnitudes) / len(magnitudes) if magnitudes else 0.0


def _maximum_subject_loss(analysis: VisualAnalysisPlan, crop: NormalizedBox | None) -> float:
    if crop is None:
        return 1.0
    track = next(item for item in analysis.subject_tracks if item.subject_id == analysis.primary_subject_id)
    return max((1.0 - _coverage(sample.box, crop) for sample in track.samples), default=1.0)


def _abstention_reasons(
    analysis: VisualAnalysisPlan,
    crop: NormalizedBox | None,
    source_crop_fraction: float,
    subject_loss: float,
    budget: CropBudget,
    min_tracking_confidence: float,
) -> tuple[str, ...]:
    track = next(item for item in analysis.subject_tracks if item.subject_id == analysis.primary_subject_id)
    reasons = []
    if track.confidence < min_tracking_confidence:
        reasons.append("tracking_confidence_below_threshold")
    if any(loss.subject_id == analysis.primary_subject_id for loss in analysis.tracking_losses):
        reasons.append("tracking_loss")
    if analysis.ambiguities:
        reasons.append("multi_subject_ambiguity")
    if crop is None:
        reasons.append("stabilization_geometry_unbounded")
    if source_crop_fraction > budget.max_source_crop_fraction + 1e-12:
        reasons.append("source_crop_budget_exceeded")
    if subject_loss > budget.max_subject_loss + 1e-12:
        reasons.append("subject_crop_budget_exceeded")
    return tuple(reasons)


def plan_stabilization(
    *,
    analysis: VisualAnalysisPlan | Mapping[str, Any],
    crop_budget: CropBudget | Mapping[str, Any],
    min_tracking_confidence: float = 0.70,
    compensation_ratio: float = 0.80,
) -> StabilizationPlan:
    """Plan evidence-backed stabilization without running a transform."""

    if not 0.0 <= min_tracking_confidence <= 1.0:
        raise ValidationError("min_tracking_confidence", "must be between 0 and 1")
    if not 0.0 < compensation_ratio <= 1.0:
        raise ValidationError("compensation_ratio", "must be greater than 0 and at most 1")
    analysis_model = VisualAnalysisPlan.model_validate(analysis)
    budget_model = CropBudget.model_validate(crop_budget)
    transforms = _transforms(analysis_model, compensation_ratio)
    required_crop = _required_crop(transforms)
    source_crop_fraction = 1.0 - required_crop.area if required_crop is not None else 1.0
    maximum_subject_loss = _maximum_subject_loss(analysis_model, required_crop)
    reasons = _abstention_reasons(
        analysis_model,
        required_crop,
        source_crop_fraction,
        maximum_subject_loss,
        budget_model,
        min_tracking_confidence,
    )
    input_motion_score = _motion_score(analysis_model)
    expected_reduction = compensation_ratio if input_motion_score > 0.0 else 0.0
    payload = {
        "analysis_sha256": analysis_model.plan_sha256,
        "source": analysis_model.source,
        "primary_subject_id": analysis_model.primary_subject_id,
        "crop_budget": budget_model,
        "min_tracking_confidence": min_tracking_confidence,
        "compensation_ratio": compensation_ratio,
        "status": "abstained" if reasons else "ready",
        "abstention_reasons": reasons,
        "transforms": transforms,
        "required_crop_box": required_crop,
        "source_crop_fraction": source_crop_fraction,
        "maximum_subject_loss": maximum_subject_loss,
        "input_motion_score": input_motion_score,
        "expected_motion_reduction": expected_reduction,
    }
    prototype = StabilizationPlan.model_construct(**payload, plan_sha256="sha256:" + "0" * 64)
    return StabilizationPlan(
        **payload,
        plan_sha256=canonical_sha256(prototype, exclude={"plan_sha256"}),
    )
