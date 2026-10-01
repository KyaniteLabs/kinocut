"""Source-bound human motion review, separate from measured proxy evidence.

A receipt records a reviewer's attestation; it cannot prove that a person
watched the film or turn a luma proxy into semantic artistic judgment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError, field_validator, model_validator

from kinocut.contracts._common import Sha256, ValueObject
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path
from kinocut.limits import MAX_TEMPORAL_INSPECTION_FRAMES, MAX_VIDEO_DURATION
from kinocut.semantic.models import canonical_digest


def _invalid_review(message: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code="invalid_motion_review")


class WatchedInterval(ValueObject):
    start: float = Field(ge=0, le=MAX_VIDEO_DURATION, strict=True)
    end: float = Field(gt=0, le=MAX_VIDEO_DURATION, strict=True)

    @model_validator(mode="after")
    def _ordered(self) -> WatchedInterval:
        if self.end <= self.start:
            raise _invalid_review("Watched intervals must have positive duration")
        return self


class MotionReview(ValueObject):
    reviewer_id: str = Field(pattern=r"^human:[a-z0-9][a-z0-9_.-]{0,63}$")
    source_sha256: Sha256
    report_sha256: Sha256
    watched_intervals: tuple[WatchedInterval, ...] = Field(min_length=1, max_length=MAX_TEMPORAL_INSPECTION_FRAMES)
    dispositions: dict[str, Literal["purposeful_motion", "intended_cut", "needs_fix"]] = Field(
        max_length=3 * MAX_TEMPORAL_INSPECTION_FRAMES
    )
    verdict: Literal["accept", "reject"]


class MotionEvidence(ValueObject):
    start: float = Field(ge=0, le=MAX_VIDEO_DURATION, strict=True)
    end: float = Field(gt=0, le=MAX_VIDEO_DURATION, strict=True)

    @model_validator(mode="after")
    def _ordered(self) -> MotionEvidence:
        if self.end <= self.start:
            raise _invalid_review("Motion evidence intervals must have positive duration")
        return self


class MotionLurchEvidence(MotionEvidence):
    code: Literal["image_change_rate_lurch"]
    rate_delta: float = Field(ge=0, strict=True)
    rate_ratio: float = Field(ge=1, strict=True)


class MotionRateEvidence(MotionEvidence):
    code: Literal["calm_to_high_image_change", "sustained_high_image_change"]
    rate: float = Field(ge=0, strict=True)


class TransitionEvidence(MotionEvidence):
    difference: float = Field(ge=0, le=255, strict=True)
    classification: Literal["isolated_transition_candidate"]
    intent_assessed: Literal[False]

    @field_validator("intent_assessed", mode="before")
    @classmethod
    def _intent_is_unassessed(cls, value):
        if value is not False:
            raise _invalid_review("Measured transitions cannot assert artistic intent")
        return value


def _validated_motion_evidence(item: dict[str, Any], kind: str, duration: float) -> None:
    model = (
        TransitionEvidence
        if kind == "transition"
        else MotionLurchEvidence
        if item.get("code") == "image_change_rate_lurch"
        else MotionRateEvidence
    )
    try:
        evidence = model.model_validate(item)
    except (ValidationError, OverflowError) as exc:
        raise _invalid_review("Motion interval evidence violates the producer schema") from exc
    if evidence.end > duration:
        raise _invalid_review("Motion interval evidence must stay within the inspected film")


def motion_review_items(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Enumerate all flagged intervals, including isolated potential cuts."""
    items = []
    duration = _bounded_media_number(report, "expected_media_end")
    for kind, field in (("finding", "findings"), ("transition", "isolated_transitions")):
        evidence = report.get(field, ())
        if not isinstance(evidence, (list, tuple)) or len(evidence) > 3 * MAX_TEMPORAL_INSPECTION_FRAMES:
            raise _invalid_review("Motion findings must be a bounded evidence sequence")
        for ordinal, item in enumerate(evidence):
            if not isinstance(item, dict):
                raise _invalid_review("Motion findings must be evidence objects")
            _validated_motion_evidence(item, kind, duration)
            body = {"kind": kind, "ordinal": ordinal, "evidence": item}
            items.append({"review_id": canonical_digest(body), **body})
    return items


def _bounded_media_number(report: dict[str, Any], field: str) -> float:
    value = report.get(field)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_VIDEO_DURATION:
        raise _invalid_review("Motion coverage must contain finite bounded numeric evidence")
    return float(value)


def _require_complete_measurements(report: dict[str, Any]) -> float:
    duration = _bounded_media_number(report, "expected_media_end")
    start = _bounded_media_number(report, "observed_start")
    last = _bounded_media_number(report, "observed_last_timestamp")
    end = _bounded_media_number(report, "decoded_media_end")
    decoded_coverage = _bounded_media_number(report, "decoded_coverage_seconds")
    difference_coverage = _bounded_media_number(report, "difference_coverage_seconds")
    count = report.get("decoded_frame_count")
    if (
        report.get("method") != "chronological_luma_change_rate.v1"
        or report.get("source_binding_status") != "hashed_media_unchanged_during_inspection"
        or report.get("coverage_scope") != "complete_bounded_decode"
        or report.get("budget_truncation") is not False
        or start != 0
        or not start < last < duration
        or end != duration
        or decoded_coverage != round(end - start, 6)
        or difference_coverage != round(last - start, 6)
        or isinstance(count, bool)
        or not isinstance(count, int)
        or not 2 <= count <= MAX_TEMPORAL_INSPECTION_FRAMES
        or any(report.get(field) for field in ("gaps", "unmeasured_intervals", "corrupt_intervals"))
    ):
        raise _invalid_review("Acceptance requires source-bound, complete, untruncated whole-film inspection")
    return duration


def _require_whole_film(report: dict[str, Any], review: MotionReview) -> float:
    duration = _require_complete_measurements(report)
    covered_until = 0.0
    for interval in sorted(review.watched_intervals, key=lambda item: item.start):
        if interval.start > covered_until or interval.end > duration:
            raise _invalid_review("Watched intervals must cover the entire film without gaps or excess")
        covered_until = max(covered_until, interval.end)
    if covered_until != duration:
        raise _invalid_review("Complete human viewing must cover the final media timestamp")
    return float(duration)


def _require_dispositions(report: dict[str, Any], review: MotionReview) -> None:
    items = motion_review_items(report)
    if set(review.dispositions) != {item["review_id"] for item in items}:
        raise _invalid_review("Every flagged motion interval and transition needs exactly one disposition")
    for item in items:
        disposition = review.dispositions[item["review_id"]]
        intended = "intended_cut" if item["kind"] == "transition" else "purposeful_motion"
        if disposition not in {intended, "needs_fix"}:
            raise _invalid_review("Motion and transition dispositions must match the measured evidence kind")
    if review.verdict == "accept" and "needs_fix" in review.dispositions.values():
        raise _invalid_review("Unresolved motion findings cannot receive acceptance")


def record_motion_acceptance(
    report: dict[str, Any],
    *,
    input_path: str,
    reviewer_id: str,
    source_sha256: str,
    report_sha256: str,
    watched_intervals: list[dict[str, float]],
    dispositions: dict[str, str],
    verdict: str,
) -> dict[str, Any]:
    """Record complete viewing and intentional exceptions against exact evidence.

    Hashes are explicit so a stale review cannot approve a changed report/file.
    The caller persists the returned receipt; inspection evidence is untouched.
    """
    if not isinstance(report, dict):
        raise _invalid_review("Motion report must be an inspection object")
    try:
        review = MotionReview.model_validate(
            {
                "reviewer_id": reviewer_id,
                "source_sha256": source_sha256,
                "report_sha256": report_sha256,
                "watched_intervals": watched_intervals,
                "dispositions": dispositions,
                "verdict": verdict,
            }
        )
        duration = _require_whole_film(report, review)
        _require_dispositions(report, review)
        if canonical_digest(report) != review.report_sha256 or report.get("source_sha256") != review.source_sha256:
            raise _invalid_review("Review hashes must match the inspected source and exact motion report")
        from kinocut.rescue.operations import _sha256

        source = Path(_validate_input_path(input_path))
        before = source.stat()
        digest = _sha256(source)
        after = source.stat()
        identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if digest != review.source_sha256 or any(
            getattr(before, key) != getattr(after, key) for key in identity_fields
        ):
            raise _invalid_review("Media identity changed since inspection or while verifying review")
    except (ValidationError, TypeError, ValueError, KeyError, RecursionError) as exc:
        raise _invalid_review("Motion review inputs or report are invalid") from exc
    receipt = {
        "artifact_kind": "motion_acceptance_receipt",
        "schema_version": 1,
        **review.model_dump(mode="json"),
        "film_duration_seconds": duration,
        "human_viewing_status": "complete_reviewer_attestation",
        "acceptance": "human_granted" if review.verdict == "accept" else "human_rejected",
        "attestation_verified_by_system": False,
        "semantic_assessment_source": "human_reviewer",
    }
    return {**receipt, "receipt_sha256": canonical_digest(receipt)}
