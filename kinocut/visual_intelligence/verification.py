"""Pure evidence verifiers for V2/V3 output measurements."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from itertools import pairwise
from typing import Any

from kinocut.errors import ValidationError

from .models import (
    BorderMeasurement,
    CoverageSample,
    MotionMeasurement,
    NormalizedBox,
    ResolutionSample,
    TimelineSyncMeasurement,
    VerificationCheck,
)


def _threshold(value: float, parameter: str, *, positive: bool = False) -> None:
    valid = value > 0.0 if positive else 0.0 <= value <= 1.0
    if not valid:
        detail = "must be greater than 0" if positive else "must be between 0 and 1"
        raise ValidationError(parameter, detail)


def _verify_coverage(
    *,
    verifier_id: str,
    failure_code: str,
    samples: Iterable[CoverageSample | Mapping[str, Any]],
    minimum_coverage: float,
) -> VerificationCheck:
    _threshold(minimum_coverage, "minimum_coverage")
    models = tuple(CoverageSample.model_validate(sample) for sample in samples)
    measured = min((sample.coverage for sample in models), default=0.0)
    failures = () if models and measured >= minimum_coverage else (failure_code,)
    return VerificationCheck(
        verifier_id=verifier_id,
        passed=not failures,
        measured=measured,
        required=minimum_coverage,
        failure_codes=failures,
    )


def verify_subject_coverage(
    *, samples: Iterable[CoverageSample | Mapping[str, Any]], minimum_coverage: float
) -> VerificationCheck:
    return _verify_coverage(
        verifier_id="subject_coverage",
        failure_code="subject_coverage_below_threshold",
        samples=samples,
        minimum_coverage=minimum_coverage,
    )


def verify_safe_zone_coverage(
    *, samples: Iterable[CoverageSample | Mapping[str, Any]], minimum_coverage: float
) -> VerificationCheck:
    return _verify_coverage(
        verifier_id="safe_zone_coverage",
        failure_code="safe_zone_coverage_below_threshold",
        samples=samples,
        minimum_coverage=minimum_coverage,
    )


def verify_crop_continuity(
    *, crop_boxes: Iterable[NormalizedBox | Mapping[str, Any]], maximum_center_step: float
) -> VerificationCheck:
    _threshold(maximum_center_step, "maximum_center_step", positive=True)
    boxes = tuple(NormalizedBox.model_validate(box) for box in crop_boxes)
    steps = (
        max(abs(current.center_x - previous.center_x), abs(current.center_y - previous.center_y))
        for previous, current in pairwise(boxes)
    )
    measured = max(steps, default=0.0)
    failures = () if boxes and measured <= maximum_center_step + 1e-12 else ("crop_discontinuity",)
    return VerificationCheck(
        verifier_id="crop_continuity",
        passed=not failures,
        measured=measured,
        required=maximum_center_step,
        failure_codes=failures,
    )


def verify_crop_resolution(
    *,
    samples: Iterable[ResolutionSample | Mapping[str, Any]],
    minimum_width: int,
    minimum_height: int,
) -> VerificationCheck:
    if minimum_width < 1 or minimum_height < 1:
        raise ValidationError("minimum_resolution", "width and height must be positive")
    models = tuple(ResolutionSample.model_validate(sample) for sample in samples)
    ratios = (min(sample.width / minimum_width, sample.height / minimum_height) for sample in models)
    measured = min(ratios, default=0.0)
    failures = () if models and measured >= 1.0 else ("resolution_below_floor",)
    return VerificationCheck(
        verifier_id="crop_resolution",
        passed=not failures,
        measured=measured,
        required=1.0,
        failure_codes=failures,
    )


def verify_motion_reduction(
    *,
    measurement: MotionMeasurement | Mapping[str, Any],
    minimum_reduction_fraction: float,
) -> VerificationCheck:
    _threshold(minimum_reduction_fraction, "minimum_reduction_fraction")
    model = MotionMeasurement.model_validate(measurement)
    measured = (model.before_score - model.after_score) / model.before_score if model.before_score else 0.0
    failures: tuple[str, ...]
    if model.before_score == 0.0:
        failures = ("motion_baseline_missing",)
    else:
        failures = () if measured >= minimum_reduction_fraction else ("motion_reduction_below_threshold",)
    return VerificationCheck(
        verifier_id="motion_reduction",
        passed=not failures,
        measured=measured,
        required=minimum_reduction_fraction,
        failure_codes=failures,
    )


def verify_borders(*, measurement: BorderMeasurement | Mapping[str, Any]) -> VerificationCheck:
    model = BorderMeasurement.model_validate(measurement)
    measured = model.frames_with_borders / model.total_frames
    failures = () if model.frames_with_borders == 0 else ("visible_borders_detected",)
    return VerificationCheck(
        verifier_id="borders",
        passed=not failures,
        measured=measured,
        required=0.0,
        failure_codes=failures,
    )


def verify_duration_and_sync(
    *,
    measurement: TimelineSyncMeasurement | Mapping[str, Any],
    duration_tolerance_seconds: float,
    sync_tolerance_seconds: float,
) -> VerificationCheck:
    _threshold(duration_tolerance_seconds, "duration_tolerance_seconds", positive=True)
    _threshold(sync_tolerance_seconds, "sync_tolerance_seconds", positive=True)
    model = TimelineSyncMeasurement.model_validate(measurement)
    duration_delta = abs(model.output_duration_seconds - model.source_duration_seconds)
    sync_delta = abs(model.output_av_offset_seconds - model.source_av_offset_seconds)
    failures = []
    if duration_delta > duration_tolerance_seconds + 1e-12:
        failures.append("duration_changed")
    if sync_delta > sync_tolerance_seconds + 1e-12:
        failures.append("av_sync_changed")
    worst_tolerance_ratio = max(
        duration_delta / duration_tolerance_seconds,
        sync_delta / sync_tolerance_seconds,
    )
    return VerificationCheck(
        verifier_id="duration_and_sync",
        passed=not failures,
        measured=worst_tolerance_ratio,
        required=1.0,
        failure_codes=tuple(failures),
    )
