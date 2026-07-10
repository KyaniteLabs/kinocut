from __future__ import annotations

import pytest

from mcp_video.visual_intelligence import (
    CameraMotion,
    CropBudget,
    CropTarget,
    FrameEvidence,
    NormalizedBox,
    SourceVideo,
    SubjectObservation,
    plan_subject_aware_reframe,
    plan_visual_analysis,
)
from mcp_video.visual_intelligence.models import ReframePlan


SOURCE_HASH = "sha256:" + "b" * 64


def _analysis(*, confidence: float = 0.9, include_ambiguity: bool = False):
    frames = []
    for index, x in enumerate((0.38, 0.43, 0.48)):
        subjects = [
            SubjectObservation(
                subject_id="subject-main",
                box=NormalizedBox(x=x, y=0.18, width=0.18, height=0.58),
                confidence=confidence,
            )
        ]
        if include_ambiguity and index == 1:
            subjects.append(
                SubjectObservation(
                    subject_id="subject-other",
                    box=NormalizedBox(x=0.12, y=0.20, width=0.16, height=0.55),
                    confidence=confidence - 0.02,
                )
            )
        frames.append(
            FrameEvidence(
                timestamp_seconds=float(index),
                subjects=tuple(subjects),
                camera_motion=CameraMotion(
                    dx=0.01,
                    dy=0.0,
                    rotation_degrees=0.0,
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
        ambiguity_confidence_delta=0.05,
    )


def test_v2_builds_subject_aware_crop_track_and_representative_previews() -> None:
    analysis = _analysis()
    plan = plan_subject_aware_reframe(
        analysis=analysis,
        targets=(
            CropTarget(
                target_id="portrait",
                aspect_width=9,
                aspect_height=16,
                output_width=1080,
                output_height=1920,
            ),
        ),
        crop_budget=CropBudget(max_subject_loss=0.05, max_source_crop_fraction=0.70),
        min_tracking_confidence=0.70,
        max_center_step=0.08,
        preview_count=3,
    )

    assert plan.schema_version == 1
    assert plan.plan_kind == "subject_aware_reframe"
    assert plan.execution_mode == "planning_only"
    assert plan.policy_id == "local_visual_transform"
    assert plan.timeline_locked is True
    assert plan.network_allowed is False
    assert plan.source_overwrite_allowed is False

    variant = plan.variants[0]
    assert variant.status == "ready"
    assert variant.abstention_reasons == ()
    assert len(variant.crop_track) == 3
    assert [preview.timestamp_seconds for preview in variant.previews] == [0.0, 1.0, 2.0]
    assert variant.source_crop_fraction == pytest.approx(0.68359375)
    assert variant.maximum_subject_loss == pytest.approx(0.0)
    assert variant.output_width == 1080
    assert variant.output_height == 1920
    for sample in variant.crop_track:
        pixel_aspect = (sample.crop_box.width * 1920) / (sample.crop_box.height * 1080)
        assert pixel_aspect == pytest.approx(9 / 16)
        assert sample.subject_coverage == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("analysis", "budget", "minimum_confidence", "reason"),
    (
        (
            _analysis(confidence=0.45),
            CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.7),
            0.7,
            "tracking_confidence_below_threshold",
        ),
        (
            _analysis(include_ambiguity=True),
            CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.7),
            0.7,
            "multi_subject_ambiguity",
        ),
        (
            _analysis(),
            CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.5),
            0.7,
            "source_crop_budget_exceeded",
        ),
    ),
)
def test_v2_abstains_when_evidence_or_crop_budget_is_unsafe(
    analysis, budget: CropBudget, minimum_confidence: float, reason: str
) -> None:
    plan = plan_subject_aware_reframe(
        analysis=analysis,
        targets=(
            CropTarget(
                target_id="portrait",
                aspect_width=9,
                aspect_height=16,
                output_width=1080,
                output_height=1920,
            ),
        ),
        crop_budget=budget,
        min_tracking_confidence=minimum_confidence,
    )

    assert plan.variants[0].status == "abstained"
    assert reason in plan.variants[0].abstention_reasons


def test_v2_public_api_accepts_json_compatible_inputs_deterministically() -> None:
    analysis = _analysis()
    target = CropTarget(
        target_id="square",
        aspect_width=1,
        aspect_height=1,
        output_width=1080,
        output_height=1080,
    )
    budget = CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.5)

    model_plan = plan_subject_aware_reframe(
        analysis=analysis,
        targets=(target,),
        crop_budget=budget,
    )
    json_plan = plan_subject_aware_reframe(
        analysis=analysis.model_dump(mode="json"),
        targets=[target.model_dump(mode="json")],
        crop_budget=budget.model_dump(mode="json"),
    )

    assert json_plan == model_plan
    assert json_plan.plan_sha256.startswith("sha256:")
    forged_plan = json_plan.model_dump(mode="json")
    forged_plan["plan_sha256"] = "sha256:" + "e" * 64
    with pytest.raises(ValueError, match="plan hash"):
        ReframePlan.model_validate(forged_plan)


def test_v2_rejects_forged_analysis_provenance() -> None:
    forged = _analysis().model_dump(mode="json")
    forged["plan_sha256"] = "sha256:" + "f" * 64

    with pytest.raises(ValueError, match="plan hash"):
        plan_subject_aware_reframe(
            analysis=forged,
            targets=(
                CropTarget(
                    target_id="square",
                    aspect_width=1,
                    aspect_height=1,
                    output_width=1080,
                    output_height=1080,
                ),
            ),
            crop_budget=CropBudget(max_subject_loss=0.1, max_source_crop_fraction=0.5),
        )
