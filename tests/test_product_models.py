from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from kinocut.product.models import (
    CandidateMoment,
    HighlightDiscoveryConfig,
    SourceSignal,
    TranscriptSegment,
    TranscriptWord,
    canonical_dedup_key,
)


def _candidate(**updates: object) -> CandidateMoment:
    excerpt = "A complete thought."
    start, end, sensitivity = 1.0, 2.0, "none"
    if "transcript_excerpt" in updates:
        excerpt = updates["transcript_excerpt"]  # type: ignore[assignment]
    if "start" in updates:
        start = updates["start"]  # type: ignore[assignment]
    if "end" in updates:
        end = updates["end"]  # type: ignore[assignment]
    if "sensitivity" in updates:
        sensitivity = updates["sensitivity"]  # type: ignore[assignment]
    data: dict[str, object] = {
        "candidate_id": "candidate",
        "start": start,
        "end": end,
        "transcript_excerpt": excerpt,
        "suggested_title": "Title",
        "suggested_hook": "Hook",
        "rationale": "Complete thought",
        "confidence": 0.8,
        "dedup_key": canonical_dedup_key(
            start=start,
            end=end,
            excerpt=excerpt,
            sensitivity=sensitivity,  # type: ignore[arg-type]
        ),
    }
    data.update(updates)
    return CandidateMoment.model_validate(data)


# --- Existing six behaviours ------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: TranscriptSegment(segment_id="s", start=1, end=1, text="x"),
        lambda: TranscriptWord(word="x", start=2, end=1, segment_id="s"),
    ],
)
def test_transcript_ranges_are_strict(build) -> None:
    with pytest.raises(ValidationError):
        build()


@pytest.mark.parametrize(
    "build",
    [
        lambda: TranscriptWord(word="x", start=0, end=1, segment_id="s", probability=1.1),
        lambda: SourceSignal(kind="scene_change", timestamp=0, score=0.5, unknown=True),
    ],
)
def test_probabilities_and_unknown_fields_fail_closed(build) -> None:
    with pytest.raises(ValidationError):
        build()


@pytest.mark.parametrize(
    "kwargs,expect_ok",
    [
        ({"unsuitable": True, "sensitivity": "strong"}, False),
        ({"unsuitable": True, "sensitivity": "unsafe"}, True),
    ],
)
def test_candidate_requires_safe_unsuitable_state(kwargs, expect_ok) -> None:
    if expect_ok:
        assert _candidate(**kwargs).unsuitable is True
    else:
        with pytest.raises(ValidationError):
            _candidate(**kwargs)


def test_candidate_is_frozen_and_json_stable() -> None:
    candidate = _candidate(source_signals=(SourceSignal(kind="audio_energy", timestamp=1, score=0.7),))
    with pytest.raises(ValidationError):
        candidate.end = 3  # type: ignore[misc]
    assert CandidateMoment.model_validate_json(candidate.model_dump_json()) == candidate


@pytest.mark.parametrize(
    "kwargs,expect_ok",
    [
        ({"max_clips": 2}, True),
        ({"min_clips": 3, "max_clips": 2}, False),
    ],
)
def test_discovery_config_bounds_are_coherent(kwargs, expect_ok) -> None:
    if expect_ok:
        assert HighlightDiscoveryConfig(**kwargs).min_clips == kwargs.get("max_clips", 3)
    else:
        with pytest.raises(ValidationError):
            HighlightDiscoveryConfig(**kwargs)


def test_dedup_key_is_semantic_and_stable() -> None:
    first = canonical_dedup_key(start=1, end=2, excerpt="  Hello   world ", sensitivity="none")
    second = canonical_dedup_key(start=1, end=2, excerpt="hello world", sensitivity="none")
    assert first == second
    assert len(first) == 16


# --- New findings ------------------------------------------------------------


def test_candidate_rejects_mismatched_dedup_key() -> None:
    with pytest.raises(ValidationError, match="dedup_key does not match"):
        _candidate(dedup_key="0123456789abcdef")


def test_candidate_accepts_pinned_known_digest() -> None:
    excerpt = "A complete thought."
    digest = canonical_dedup_key(start=1.0, end=2.0, excerpt=excerpt, sensitivity="none")
    assert _candidate(transcript_excerpt=excerpt, dedup_key=digest).dedup_key == digest


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_candidate_rejects_non_finite_numeric(value: float) -> None:
    with pytest.raises(ValidationError):
        _candidate(confidence=value)


@pytest.mark.parametrize(
    "min_dur,max_dur",
    [(10.0, 10.0), (20.0, 10.0)],
)
def test_discovery_config_rejects_max_le_min(min_dur: float, max_dur: float) -> None:
    with pytest.raises(ValidationError, match="max_duration"):
        HighlightDiscoveryConfig(min_duration=min_dur, max_duration=max_dur)
