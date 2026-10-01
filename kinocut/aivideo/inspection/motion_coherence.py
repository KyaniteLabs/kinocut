"""Advisory chronological image-change QA over already decoded observations.

Luma difference per second is an image-change proxy, not physical motion,
optical flow, a learned semantic assessment, or evidence of artistic intent.
"""

from __future__ import annotations

import statistics
from itertools import pairwise
from typing import Any

from kinocut.defaults import (
    DEFAULT_MOTION_COHERENCE_CALM_RATE,
    DEFAULT_MOTION_COHERENCE_HIGH_RATE,
    DEFAULT_MOTION_COHERENCE_LURCH_DELTA,
    DEFAULT_MOTION_COHERENCE_LURCH_RATIO,
    DEFAULT_MOTION_COHERENCE_SUSTAINED_WINDOWS,
    DEFAULT_MOTION_COHERENCE_TRANSITION_DIFFERENCE,
    DEFAULT_MOTION_COHERENCE_WINDOW_SECONDS,
    DEFAULT_TEMPORAL_LATE_FRAME_GAP_MULTIPLIER,
)


def _chronological_windows(frames: tuple[Any, ...]) -> tuple[list[dict], list[dict], float, list[dict]]:
    """Aggregate timestamp-weighted intervals; retain isolated transitions separately."""
    durations = [right.timestamp - left.timestamp for left, right in pairwise(frames)]
    cadence = statistics.median(durations) if durations else 0.0
    buckets: dict[int, list[float]] = {}
    transitions, coverage = [], 0.0
    gaps = []
    width = DEFAULT_MOTION_COHERENCE_WINDOW_SECONDS
    for index in range(1, len(frames)):
        left, right = frames[index - 1], frames[index]
        duration = right.timestamp - left.timestamp
        if duration > cadence * DEFAULT_TEMPORAL_LATE_FRAME_GAP_MULTIPLIER:
            gaps.append({"start": left.timestamp, "end": right.timestamp, "reason": "timestamp_gap_excluded"})
            continue  # Missing spans must never be interpolated into measured coverage.
        difference = right.difference_from_previous
        isolated = difference >= DEFAULT_MOTION_COHERENCE_TRANSITION_DIFFERENCE and (
            frames[index - 1].difference_from_previous < DEFAULT_MOTION_COHERENCE_TRANSITION_DIFFERENCE
            and (
                index + 1 == len(frames)
                or frames[index + 1].difference_from_previous < DEFAULT_MOTION_COHERENCE_TRANSITION_DIFFERENCE
            )
        )
        coverage += duration
        if isolated:
            transitions.append(
                {
                    "start": left.timestamp,
                    "end": right.timestamp,
                    "difference": difference,
                    "classification": "isolated_transition_candidate",
                    "intent_assessed": False,
                }
            )
            continue
        start = left.timestamp
        while start < right.timestamp:
            key = int(start / width)
            end = min(right.timestamp, (key + 1) * width)
            if end <= start:  # Floating-point boundary cannot stall this loop.
                key += 1
                end = min(right.timestamp, (key + 1) * width)
            bucket = buckets.setdefault(key, [0.0, 0.0])
            bucket[0] += difference * (end - start) / duration
            bucket[1] += end - start
            start = end
    windows = [
        {
            "start": max(key * width, frames[0].timestamp),
            "end": min((key + 1) * width, frames[-1].timestamp),
            "measured_seconds": round(duration, 6),
            "rate": round(total / duration, 6),
        }
        for key, (total, duration) in sorted(buckets.items())
    ]
    return windows, transitions, coverage, gaps


def _chronological_findings(windows: list[dict]) -> list[dict]:
    findings, high_run, calm_run = [], [], []
    for index, window in enumerate(windows):
        previous = windows[index - 1] if index else None
        contiguous = previous is not None and previous["end"] == window["start"]
        if not contiguous:
            high_run, calm_run = [], []
        rate = window["rate"]
        if contiguous:
            delta = abs(rate - previous["rate"])
            ratio = max(rate, previous["rate"]) / max(DEFAULT_MOTION_COHERENCE_CALM_RATE, min(rate, previous["rate"]))
            if delta >= DEFAULT_MOTION_COHERENCE_LURCH_DELTA and ratio >= DEFAULT_MOTION_COHERENCE_LURCH_RATIO:
                findings.append(
                    {
                        "code": "image_change_rate_lurch",
                        "start": previous["start"],
                        "end": window["end"],
                        "rate_delta": round(delta, 6),
                        "rate_ratio": round(ratio, 6),
                    }
                )
        if rate >= DEFAULT_MOTION_COHERENCE_HIGH_RATE:
            if len(calm_run) >= DEFAULT_MOTION_COHERENCE_SUSTAINED_WINDOWS:
                findings.append(
                    {
                        "code": "calm_to_high_image_change",
                        "start": calm_run[0]["start"],
                        "end": window["end"],
                        "rate": rate,
                    }
                )
            high_run.append(window)
            calm_run = []
            if len(high_run) == DEFAULT_MOTION_COHERENCE_SUSTAINED_WINDOWS:
                findings.append(
                    {
                        "code": "sustained_high_image_change",
                        "start": high_run[0]["start"],
                        "end": window["end"],
                        "rate": rate,
                    }
                )
            elif len(high_run) > DEFAULT_MOTION_COHERENCE_SUSTAINED_WINDOWS:
                # Extend the same sustained interval instead of duplicating it.
                for finding in reversed(findings):
                    if finding["code"] == "sustained_high_image_change":
                        finding["end"] = window["end"]
                        break
        else:
            high_run = []
            calm_run = [*calm_run, window] if rate <= DEFAULT_MOTION_COHERENCE_CALM_RATE else []
    return findings


def chronological_motion_report(frames: tuple[Any, ...], expected_end: float) -> dict[str, Any]:
    """Report measured chronology; deliberate calm is valid and human watch remains required."""
    windows, transitions, coverage, gaps = _chronological_windows(frames)
    report = {
        "method": "chronological_luma_change_rate.v1",
        "scope": "decoded_image_change_proxy; semantic_and_artistic_coherence_not_assessed",
        "assessment_status": "advisory_measured" if windows else "insufficient_motion_observations",
        "source_sha256": None,
        "source_binding_status": "unbound_observations",
        "decoded_frame_count": len(frames),
        "observed_start": frames[0].timestamp,
        "observed_last_timestamp": frames[-1].timestamp,
        "expected_media_end": expected_end,
        "difference_coverage_seconds": round(coverage, 6),
        "unmeasured_intervals": gaps,
        "coverage_scope": "provided_observations_only; timestamp_gaps_excluded",
        "budget_truncation": False,
        "units": "mean_absolute_luma_change_per_second",
        "thresholds": {
            "window_seconds": DEFAULT_MOTION_COHERENCE_WINDOW_SECONDS,
            "lurch_ratio": DEFAULT_MOTION_COHERENCE_LURCH_RATIO,
            "lurch_delta": DEFAULT_MOTION_COHERENCE_LURCH_DELTA,
            "high_rate": DEFAULT_MOTION_COHERENCE_HIGH_RATE,
            "calm_rate": DEFAULT_MOTION_COHERENCE_CALM_RATE,
            "sustained_windows": DEFAULT_MOTION_COHERENCE_SUSTAINED_WINDOWS,
            "isolated_transition_difference": DEFAULT_MOTION_COHERENCE_TRANSITION_DIFFERENCE,
        },
        "windows": windows,
        "isolated_transitions": transitions,
        "findings": _chronological_findings(windows),
        "intentional_calm_is_valid": True,
        "complete_human_viewing_required": True,
        "human_viewing_status": "not_recorded",
        "acceptance": "not_granted",
    }
    from .motion_acceptance import motion_review_items

    return {**report, "review_items": motion_review_items(report)}
