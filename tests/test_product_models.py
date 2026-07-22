from __future__ import annotations

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


def test_transcript_ranges_are_strict() -> None:
    with pytest.raises(ValidationError):
        TranscriptSegment(segment_id="s", start=1, end=1, text="x")
    with pytest.raises(ValidationError):
        TranscriptWord(word="x", start=2, end=1, segment_id="s")


def test_probabilities_and_unknown_fields_fail_closed() -> None:
    with pytest.raises(ValidationError):
        TranscriptWord(word="x", start=0, end=1, segment_id="s", probability=1.1)
    with pytest.raises(ValidationError):
        SourceSignal(kind="scene_change", timestamp=0, score=0.5, unknown=True)


def _candidate(**updates: object) -> CandidateMoment:
    data: dict[str, object] = {
        "candidate_id": "candidate",
        "start": 1.0,
        "end": 2.0,
        "transcript_excerpt": "A complete thought.",
        "suggested_title": "Title",
        "suggested_hook": "Hook",
        "rationale": "Complete thought",
        "confidence": 0.8,
        "dedup_key": "0123456789abcdef",
    }
    data.update(updates)
    return CandidateMoment.model_validate(data)


def test_candidate_requires_safe_unsuitable_state() -> None:
    with pytest.raises(ValidationError):
        _candidate(unsuitable=True, sensitivity="strong")
    assert _candidate(unsuitable=True, sensitivity="unsafe").unsuitable is True


def test_candidate_is_frozen_and_json_stable() -> None:
    candidate = _candidate(source_signals=(SourceSignal(kind="audio_energy", timestamp=1, score=0.7),))
    with pytest.raises(ValidationError):
        candidate.end = 3  # type: ignore[misc]
    assert CandidateMoment.model_validate_json(candidate.model_dump_json()) == candidate


def test_discovery_config_bounds_are_coherent() -> None:
    assert HighlightDiscoveryConfig(max_clips=2).min_clips == 2
    with pytest.raises(ValidationError):
        HighlightDiscoveryConfig(min_clips=3, max_clips=2)


def test_dedup_key_is_semantic_and_stable() -> None:
    first = canonical_dedup_key(start=1, end=2, excerpt="  Hello   world ", sensitivity="none")
    second = canonical_dedup_key(start=1, end=2, excerpt="hello world", sensitivity="none")
    assert first == second
    assert len(first) == 16
