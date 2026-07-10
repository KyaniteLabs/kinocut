from __future__ import annotations

import pytest

from mcp_video.visual_intelligence import (
    verify_borders,
    verify_crop_continuity,
    verify_crop_resolution,
    verify_duration_and_sync,
    verify_motion_reduction,
    verify_safe_zone_coverage,
    verify_subject_coverage,
)


@pytest.mark.parametrize(
    ("verifier", "verifier_id", "failure_code"),
    (
        (verify_subject_coverage, "subject_coverage", "subject_coverage_below_threshold"),
        (verify_safe_zone_coverage, "safe_zone_coverage", "safe_zone_coverage_below_threshold"),
    ),
)
def test_coverage_verifiers_gate_the_minimum_observed_coverage(verifier, verifier_id: str, failure_code: str) -> None:
    passing = verifier(
        samples=[
            {"timestamp_seconds": 0.0, "coverage": 1.0},
            {"timestamp_seconds": 1.0, "coverage": 0.96},
        ],
        minimum_coverage=0.95,
    )
    failing = verifier(
        samples=[{"timestamp_seconds": 0.0, "coverage": 0.90}],
        minimum_coverage=0.95,
    )

    assert passing.verifier_id == verifier_id
    assert passing.passed is True
    assert passing.measured == pytest.approx(0.96)
    assert failing.passed is False
    assert failing.failure_codes == (failure_code,)


def test_crop_continuity_and_resolution_are_independent_gates() -> None:
    continuous = verify_crop_continuity(
        crop_boxes=[
            {"x": 0.20, "y": 0.10, "width": 0.50, "height": 0.80},
            {"x": 0.25, "y": 0.12, "width": 0.50, "height": 0.80},
        ],
        maximum_center_step=0.06,
    )
    discontinuous = verify_crop_continuity(
        crop_boxes=[
            {"x": 0.10, "y": 0.10, "width": 0.50, "height": 0.80},
            {"x": 0.30, "y": 0.10, "width": 0.50, "height": 0.80},
        ],
        maximum_center_step=0.06,
    )
    resolution = verify_crop_resolution(
        samples=[
            {"timestamp_seconds": 0.0, "width": 1080, "height": 1920},
            {"timestamp_seconds": 1.0, "width": 1079, "height": 1920},
        ],
        minimum_width=1080,
        minimum_height=1920,
    )

    assert continuous.passed is True
    assert discontinuous.passed is False
    assert discontinuous.failure_codes == ("crop_discontinuity",)
    assert resolution.passed is False
    assert resolution.failure_codes == ("resolution_below_floor",)


def test_stabilization_motion_and_border_verifiers_require_measured_improvement() -> None:
    motion = verify_motion_reduction(
        measurement={"before_score": 10.0, "after_score": 4.0},
        minimum_reduction_fraction=0.50,
    )
    borders = verify_borders(measurement={"total_frames": 300, "frames_with_borders": 1})

    assert motion.passed is True
    assert motion.measured == pytest.approx(0.60)
    assert borders.passed is False
    assert borders.failure_codes == ("visible_borders_detected",)


def test_duration_and_sync_verifier_preserves_timeline_and_av_offset() -> None:
    passing = verify_duration_and_sync(
        measurement={
            "source_duration_seconds": 10.0,
            "output_duration_seconds": 10.01,
            "source_av_offset_seconds": 0.02,
            "output_av_offset_seconds": 0.025,
        },
        duration_tolerance_seconds=0.02,
        sync_tolerance_seconds=0.01,
    )
    failing = verify_duration_and_sync(
        measurement={
            "source_duration_seconds": 10.0,
            "output_duration_seconds": 9.8,
            "source_av_offset_seconds": 0.02,
            "output_av_offset_seconds": 0.08,
        },
        duration_tolerance_seconds=0.02,
        sync_tolerance_seconds=0.01,
    )

    assert passing.passed is True
    assert failing.passed is False
    assert failing.failure_codes == ("duration_changed", "av_sync_changed")

    sync_only_failure = verify_duration_and_sync(
        measurement={
            "source_duration_seconds": 10.0,
            "output_duration_seconds": 10.0,
            "source_av_offset_seconds": 0.02,
            "output_av_offset_seconds": 0.04,
        },
        duration_tolerance_seconds=0.02,
        sync_tolerance_seconds=0.01,
    )
    assert sync_only_failure.passed is False
    assert sync_only_failure.measured == pytest.approx(2.0)
    assert sync_only_failure.required == 1.0
