from __future__ import annotations

import pytest

from mcp_video.visual_intelligence import (
    CameraMotion,
    CropBudget,
    FrameEvidence,
    NormalizedBox,
    SourceVideo,
    SubjectObservation,
    plan_stabilization,
    plan_visual_analysis,
)
from mcp_video.visual_intelligence.models import StabilizationPlan


SOURCE_HASH = "sha256:" + "c" * 64


def _analysis(*, confidence: float = 0.92, motion_scale: float = 1.0):
    motions = ((0.02, -0.01, 0.3), (-0.015, 0.012, -0.2), (0.01, -0.005, 0.1))
    frames = []
    for index, (dx, dy, rotation) in enumerate(motions):
        frames.append(
            FrameEvidence(
                timestamp_seconds=float(index),
                subjects=(
                    SubjectObservation(
                        subject_id="subject-main",
                        box=NormalizedBox(x=0.40, y=0.20, width=0.20, height=0.55),
                        confidence=confidence,
                    ),
                ),
                camera_motion=CameraMotion(
                    dx=dx * motion_scale,
                    dy=dy * motion_scale,
                    rotation_degrees=rotation * motion_scale,
                    confidence=0.9,
                ),
            )
        )
    return plan_visual_analysis(
        source=SourceVideo(
            sha256=SOURCE_HASH,
            width=1920,
            height=1080,
            duration_seconds=2.0,
        ),
        frames=frames,
        primary_subject_id="subject-main",
    )


def test_v3_plans_counter_motion_and_declares_required_crop() -> None:
    plan = plan_stabilization(
        analysis=_analysis(),
        crop_budget=CropBudget(max_subject_loss=0.05, max_source_crop_fraction=0.20),
        min_tracking_confidence=0.70,
        compensation_ratio=0.80,
    )

    assert plan.schema_version == 1
    assert plan.plan_kind == "advanced_stabilization"
    assert plan.execution_mode == "planning_only"
    assert plan.policy_id == "local_visual_transform"
    assert plan.timeline_locked is True
    assert plan.sync_locked is True
    assert plan.status == "ready"
    assert plan.abstention_reasons == ()
    assert plan.required_crop_box is not None
    assert plan.source_crop_fraction < 0.20
    assert plan.maximum_subject_loss == pytest.approx(0.0)
    assert plan.expected_motion_reduction == pytest.approx(0.80)
    assert plan.transforms[0].translate_x == pytest.approx(-0.016)
    assert plan.transforms[0].translate_y == pytest.approx(0.008)
    assert plan.transforms[0].rotation_degrees == pytest.approx(-0.24)


@pytest.mark.parametrize(
    ("analysis", "budget", "minimum_confidence", "reason"),
    (
        (
            _analysis(confidence=0.4),
            CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.2),
            0.7,
            "tracking_confidence_below_threshold",
        ),
        (
            _analysis(motion_scale=10.0),
            CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.1),
            0.7,
            "source_crop_budget_exceeded",
        ),
    ),
)
def test_v3_abstains_when_tracking_or_crop_budget_is_exceeded(
    analysis, budget: CropBudget, minimum_confidence: float, reason: str
) -> None:
    plan = plan_stabilization(
        analysis=analysis,
        crop_budget=budget,
        min_tracking_confidence=minimum_confidence,
    )

    assert plan.status == "abstained"
    assert reason in plan.abstention_reasons


def test_v3_public_api_accepts_json_compatible_inputs_deterministically() -> None:
    analysis = _analysis()
    budget = CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.2)
    model_plan = plan_stabilization(analysis=analysis, crop_budget=budget)
    json_plan = plan_stabilization(
        analysis=analysis.model_dump(mode="json"),
        crop_budget=budget.model_dump(mode="json"),
    )

    assert json_plan == model_plan
    assert json_plan.plan_sha256.startswith("sha256:")
    forged = json_plan.model_dump(mode="json")
    forged["plan_sha256"] = "sha256:" + "d" * 64
    with pytest.raises(ValueError, match="plan hash"):
        StabilizationPlan.model_validate(forged)
