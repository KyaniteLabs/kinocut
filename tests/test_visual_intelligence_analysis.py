from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from mcp_video.errors import ValidationError
from mcp_video.visual_intelligence import (
    CameraMotion,
    FrameEvidence,
    Landmark,
    LandmarkKind,
    NormalizedBox,
    SafeRegion,
    SafeRegionKind,
    SourceVideo,
    SubjectObservation,
    VisualAnalysisPlan,
    plan_visual_analysis,
)


SOURCE_HASH = "sha256:" + "a" * 64


def _subject(
    subject_id: str,
    confidence: float,
    box: NormalizedBox,
    *,
    face_landmarks: tuple[Landmark, ...] = (),
) -> SubjectObservation:
    return SubjectObservation(
        subject_id=subject_id,
        box=box,
        confidence=confidence,
        face_landmarks=face_landmarks,
    )


def _analysis_frames(*, reverse_first_frame: bool = False) -> tuple[FrameEvidence, ...]:
    primary = _subject(
        "subject-1",
        0.90,
        NormalizedBox(x=0.10, y=0.20, width=0.40, height=0.50),
        face_landmarks=(Landmark(name="nose", kind=LandmarkKind.FACE, x=0.30, y=0.35, confidence=0.88),),
    )
    secondary = _subject(
        "subject-2",
        0.85,
        NormalizedBox(x=0.60, y=0.20, width=0.25, height=0.45),
    )
    first_subjects = (secondary, primary) if reverse_first_frame else (primary, secondary)
    crop = NormalizedBox(x=0.25, y=0.0, width=0.50, height=1.0)
    return (
        FrameEvidence(
            timestamp_seconds=0.0,
            subjects=first_subjects,
            camera_motion=CameraMotion(dx=0.02, dy=-0.01, rotation_degrees=0.4, confidence=0.91),
            safe_regions=(
                SafeRegion(
                    region_id="lower-third",
                    kind=SafeRegionKind.TEXT,
                    box=NormalizedBox(x=0.20, y=0.72, width=0.60, height=0.20),
                    confidence=0.95,
                ),
            ),
            candidate_crop=crop,
        ),
        FrameEvidence(
            timestamp_seconds=1.0,
            subjects=(secondary,),
            camera_motion=CameraMotion(dx=0.01, dy=-0.01, rotation_degrees=0.2, confidence=0.89),
            candidate_crop=crop,
        ),
        FrameEvidence(
            timestamp_seconds=2.0,
            subjects=(
                _subject(
                    "subject-1",
                    0.60,
                    NormalizedBox(x=0.12, y=0.20, width=0.40, height=0.50),
                ),
            ),
            camera_motion=CameraMotion(dx=0.0, dy=0.0, rotation_degrees=0.0, confidence=0.93),
            candidate_crop=crop,
        ),
    )


def test_v1_analysis_surfaces_tracks_landmarks_motion_losses_and_ambiguity() -> None:
    plan = plan_visual_analysis(
        source=SourceVideo(
            sha256=SOURCE_HASH,
            width=1920,
            height=1080,
            duration_seconds=2.0,
        ),
        frames=_analysis_frames(),
        primary_subject_id="subject-1",
        ambiguity_confidence_delta=0.10,
    )

    assert plan.schema_version == 1
    assert plan.plan_kind == "visual_analysis"
    assert plan.execution_mode == "planning_only"
    assert plan.local_only is True
    assert plan.identity_inference is False
    assert [track.subject_id for track in plan.subject_tracks] == ["subject-1", "subject-2"]

    primary = plan.subject_tracks[0]
    assert primary.confidence == pytest.approx(0.50)
    assert primary.coverage_ratio == pytest.approx(2 / 3)
    assert primary.samples[0].face_landmarks[0].name == "nose"
    assert [(loss.subject_id, loss.timestamp_seconds) for loss in plan.tracking_losses] == [
        ("subject-1", 1.0),
        ("subject-2", 2.0),
    ]
    assert plan.ambiguities[0].subject_ids == ("subject-1", "subject-2")
    assert plan.camera_motion[0].dx == 0.02
    assert plan.safe_regions[0].regions[0].region_id == "lower-third"

    first_loss = plan.crop_loss_estimates[0]
    assert first_loss.available is True
    assert first_loss.subject_id == "subject-1"
    assert first_loss.subject_loss == pytest.approx(0.375)
    assert plan.crop_loss_estimates[1].available is False
    assert plan.crop_loss_estimates[1].reason == "primary_subject_not_observed"


def test_v1_analysis_is_canonical_and_rejects_identity_or_duplicate_timestamps() -> None:
    source = SourceVideo(sha256=SOURCE_HASH, width=1920, height=1080, duration_seconds=2.0)
    first = plan_visual_analysis(
        source=source,
        frames=_analysis_frames(),
        primary_subject_id="subject-1",
    )
    reordered = plan_visual_analysis(
        source=source,
        frames=_analysis_frames(reverse_first_frame=True),
        primary_subject_id="subject-1",
    )

    assert first.plan_sha256 == reordered.plan_sha256
    assert first.model_dump() == reordered.model_dump()
    assert first.plan_sha256.startswith("sha256:")

    with pytest.raises(PydanticValidationError, match="identity"):
        SubjectObservation(
            subject_id="subject-1",
            box=NormalizedBox(x=0.1, y=0.1, width=0.2, height=0.2),
            confidence=0.9,
            identity="person-name",  # type: ignore[call-arg]
        )

    frames = _analysis_frames()
    with pytest.raises(ValidationError, match="timestamps must be unique"):
        plan_visual_analysis(
            source=source,
            frames=(frames[0], frames[0]),
            primary_subject_id="subject-1",
        )


def test_v1_public_api_accepts_json_compatible_inputs() -> None:
    source = SourceVideo(sha256=SOURCE_HASH, width=1920, height=1080, duration_seconds=2.0)
    frames = _analysis_frames()
    expected = plan_visual_analysis(
        source=source,
        frames=frames,
        primary_subject_id="subject-1",
    )

    actual = plan_visual_analysis(
        source=source.model_dump(mode="json"),
        frames=[frame.model_dump(mode="json") for frame in frames],
        primary_subject_id="subject-1",
    )

    assert actual == expected
    assert actual.model_dump(mode="json")["execution_mode"] == "planning_only"


def test_v1_rejects_forged_digest_and_non_finite_motion() -> None:
    source = SourceVideo(sha256=SOURCE_HASH, width=1920, height=1080, duration_seconds=2.0)
    plan = plan_visual_analysis(
        source=source,
        frames=_analysis_frames(),
        primary_subject_id="subject-1",
    )
    forged = plan.model_dump()
    forged["plan_sha256"] = "sha256:" + "f" * 64

    with pytest.raises(PydanticValidationError, match="plan hash"):
        VisualAnalysisPlan.model_validate(forged)

    invalid_frame = _analysis_frames()[0].model_dump()
    invalid_frame["camera_motion"]["dx"] = float("nan")
    with pytest.raises(PydanticValidationError):
        plan_visual_analysis(
            source=source,
            frames=(invalid_frame,),
            primary_subject_id="subject-1",
        )
