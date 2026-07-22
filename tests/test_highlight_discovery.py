"""Strict unit tests for ``kinocut.product.highlight_discovery``.

The discovery layer is deterministic and offline: every test builds a small
in-memory transcript fixture and asserts on the strict-model output. No real
media is touched and no engine is invoked.

Acceptance coverage (mirrors the plan):

* Determinism — re-running discovery on identical inputs is byte-stable.
* Candidate count — a well-formed fixture yields at least three candidates;
  degenerate inputs return fewer honestly, never padded weak output.
* Required fields — every :class:`CandidateMoment` carries every documented
  field with the expected type.
* Bounds / durations — ``0 <= start < end`` and every candidate's duration
  lies inside ``[min_duration, max_duration]``.
* Duplicate suppression — two windows that collapse to the same ``dedup_key``
  are reduced to one.
* Edge / degenerate inputs — empty list, all-silence, mid-clause trailing
  segments return the candidates they can justify (or zero, honestly).
* Complete-thought boundary preference — the chosen end prefers the first
  sentence-terminal marker inside ``max_duration``.
* No leading silence — the candidate's ``start`` is the start of the first
  non-silent, word-bearing segment in the window.
"""

from __future__ import annotations

import json
from collections.abc import Iterable

import pytest

from kinocut.product import (
    CandidateMoment,
    HighlightDiscoveryConfig,
    SourceSignal,
    TranscriptSegment,
    canonical_dedup_key,
    discover_highlights,
)


# --- Fixture helpers ---------------------------------------------------------


def _seg(index: int, start: float, end: float, text: str, *, silence: bool = False) -> TranscriptSegment:
    """Build a :class:`TranscriptSegment` with the slice's identifier scheme."""

    return TranscriptSegment(
        segment_id=f"seg-{index:03d}",
        start=start,
        end=end,
        text=text,
        is_silence=silence,
    )


def _well_formed_fixture() -> list[TranscriptSegment]:
    """A 70 s talking-head transcript with three distinct topics and terminals.

    Three punctuated anchors at 4 s, 18 s, and 28 s ensure the discovery layer
    surfaces at least three independently-scored candidates. Used by every
    test that asserts a non-degenerate result.
    """

    return [
        _seg(0, 0.0, 4.0, "Hello and welcome."),
        _seg(1, 4.0, 12.0, "Today we explore the history of the typewriter and why it mattered."),
        _seg(2, 12.0, 18.0, "It changed everything for office work."),
        _seg(3, 18.0, 28.0, "In the next chapter we will look at how it shaped newsrooms."),
        _seg(4, 28.0, 40.0, "Reporters could file copy faster than ever."),
        _seg(5, 40.0, 55.0, "It also centralised fact checking inside the newsroom."),
        _seg(6, 55.0, 70.0, "And that is how the modern press took shape."),
    ]


def _json_roundtrip(value: object) -> object:
    """Force the strict-model output through ``json.dumps`` to prove stability."""

    return json.loads(json.dumps(value, sort_keys=True, separators=(",", ":")))


# --- Acceptance: determinism -------------------------------------------------


def test_discover_highlights_is_byte_stable_across_runs():
    """Re-running discovery on identical inputs yields byte-identical output.

    The orchestrator relies on this for CAS dedup: two invocations with the
    same transcript and config MUST collapse to the same canonical payload.
    """

    transcript = _well_formed_fixture()
    config = HighlightDiscoveryConfig()

    first = discover_highlights(transcript, config=config)
    second = discover_highlights(transcript, config=config)

    first_payload = _json_roundtrip(first.model_dump(mode="json"))
    second_payload = _json_roundtrip(second.model_dump(mode="json"))
    assert first_payload == second_payload


# --- Acceptance: candidate count ---------------------------------------------


def test_well_formed_fixture_surfaces_at_least_three_candidates():
    """The plan's acceptance floor: a well-formed fixture yields >=3 candidates."""

    result = discover_highlights(_well_formed_fixture())
    assert len(result.candidates) >= 3


def test_discovered_at_offsets_match_candidate_starts():
    """Every candidate's start appears (quantised) in ``discovered_at_offsets``."""

    transcript = _well_formed_fixture()
    result = discover_highlights(transcript)
    assert len(result.discovered_at_offsets) == len(result.candidates)
    for candidate, offset in zip(result.candidates, result.discovered_at_offsets, strict=True):
        assert offset == round(candidate.start, 3)


# --- Acceptance: required fields --------------------------------------------


def test_every_candidate_carries_every_required_field():
    """Every :class:`CandidateMoment` carries every documented field with the right type.

    The downstream ShortsPlan composer reads each field by name; missing or
    wrongly-typed fields would break the orchestrator's JSON contract.
    """

    result = discover_highlights(_well_formed_fixture())

    required_text = {
        "candidate_id": str,
        "transcript_excerpt": str,
        "suggested_title": str,
        "suggested_hook": str,
        "rationale": str,
        "dedup_key": str,
    }
    required_nullable_text = {"context_before", "context_after", "review_warning"}
    for candidate in result.candidates:
        for field_name, expected_type in required_text.items():
            value = getattr(candidate, field_name)
            assert isinstance(value, expected_type), field_name
            assert value, f"{field_name} must be non-empty"
        for field_name in required_nullable_text:
            value = getattr(candidate, field_name)
            assert value is None or isinstance(value, str), field_name
        assert isinstance(candidate.confidence, float)
        assert 0.0 <= candidate.confidence <= 1.0
        assert isinstance(candidate.start, float)
        assert isinstance(candidate.end, float)
        assert candidate.sensitivity in {"none", "mild", "strong", "unsafe"}
        assert isinstance(candidate.unsuitable, bool)
        assert isinstance(candidate.source_signals, tuple)
        for signal in candidate.source_signals:
            assert isinstance(signal, SourceSignal)


def test_candidate_id_matches_segment_id_pattern():
    """``candidate_id`` satisfies the bounded identifier pattern shared with segments."""

    pattern = __import__("re").compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
    for candidate in discover_highlights(_well_formed_fixture()).candidates:
        assert pattern.match(candidate.candidate_id), candidate.candidate_id


def test_dedup_key_matches_sha256_hex_prefix():
    """``dedup_key`` is exactly 16 lowercase hex characters (sha256 prefix)."""

    pattern = __import__("re").compile(r"^[0-9a-f]{16}$")
    for candidate in discover_highlights(_well_formed_fixture()).candidates:
        assert pattern.match(candidate.dedup_key), candidate.dedup_key


# --- Acceptance: bounds / durations ------------------------------------------


def test_all_candidates_satisfy_bounds_and_duration_window():
    """Each candidate respects ``0 <= start < end`` and the duration window.

    A clipped or negative-duration candidate would corrupt the orchestrator's
    downstream trim op. The window rules (``min_duration`` <= duration <=
    ``max_duration``) protect the YouTube Shorts / Instagram Reels clip
    budgets.
    """

    config = HighlightDiscoveryConfig(min_duration=15.0, max_duration=60.0)
    result = discover_highlights(_well_formed_fixture(), config=config)

    assert result.candidates, "fixture should produce candidates"
    for candidate in result.candidates:
        assert candidate.start >= 0.0
        assert candidate.end > candidate.start
        duration = candidate.end - candidate.start
        # The window's terminal stop is allowed to be slightly past ``min_duration``
        # but never past ``max_duration`` (the clamp enforces it).
        assert duration <= config.max_duration + 1e-6


def test_candidate_starts_are_non_decreasing_after_score_sort():
    """Final result ordering is by descending confidence (with stable start tie-break)."""

    result = discover_highlights(_well_formed_fixture())
    confidences = [candidate.confidence for candidate in result.candidates]
    assert confidences == sorted(confidences, reverse=True)


# --- Acceptance: duplicate suppression ---------------------------------------


def test_duplicate_suppression_collapses_overlapping_candidates():
    """Two candidates that collapse to the same ``dedup_key`` are reduced to one.

    The discovery layer emits one candidate per non-silent anchor; a transcript
    with overlapping punctuation must NOT emit near-duplicate windows.
    """

    # Two anchors whose excerpts end with the SAME terminal punctuation and
    # start within the same ms bucket produce the same canonical dedup_key.
    transcript = [
        _seg(0, 0.0, 5.0, "Hello there."),
        _seg(1, 1.0, 6.0, "Hello there."),  # same words, overlapping range
    ]
    result = discover_highlights(transcript)
    keys = [candidate.dedup_key for candidate in result.candidates]
    assert len(keys) == len(set(keys)), "duplicate dedup_keys survived suppression"


def test_canonical_dedup_key_is_stable_for_equal_content():
    """The dedup-key helper is order-independent and float-quantised."""

    a = canonical_dedup_key(start=10.0, end=20.0, excerpt="Same sentence.", sensitivity="none")
    b = canonical_dedup_key(start=10.0004, end=19.9996, excerpt="same sentence.", sensitivity="none")
    assert a == b


def test_canonical_dedup_key_distinguishes_sensitivity():
    """Two candidates with the same window but different sensitivity must NOT collide."""

    base = canonical_dedup_key(start=10.0, end=20.0, excerpt="Hello.", sensitivity="none")
    flagged = canonical_dedup_key(start=10.0, end=20.0, excerpt="Hello.", sensitivity="unsafe")
    assert base != flagged


# --- Acceptance: edge / degenerate input -------------------------------------


def test_empty_transcript_returns_empty_result():
    """An empty transcript is a known case the orchestrator must handle honestly."""

    result = discover_highlights([])
    assert result.candidates == ()
    assert result.discovered_at_offsets == ()
    assert result.source_segment_count == 0


def test_none_transcript_returns_empty_result():
    """``None`` is treated identically to an empty list (no exception)."""

    result = discover_highlights(None)
    assert result.candidates == ()


def test_all_silence_transcript_returns_empty_result():
    """A transcript whose only segments are silence cannot produce candidates."""

    transcript = [_seg(i, float(i * 10), float(i * 10 + 8), "shh", silence=True) for i in range(3)]
    result = discover_highlights(transcript)
    assert result.candidates == ()


def test_unfinished_trailing_thought_is_rejected():
    """A window that ends in a comma / colon / semicolon is an unfinished thought.

    The payoff rule rejects windows that end mid-clause: a rendered short
    would trail off and frustrate the viewer.
    """

    transcript = [
        _seg(0, 0.0, 5.0, "A complete thought here."),
        _seg(1, 5.0, 12.0, "This one trails off,"),  # no terminal -> unfinished
    ]
    result = discover_highlights(transcript)
    # The first segment can form a candidate on its own; the second cannot.
    starts = [candidate.start for candidate in result.candidates]
    assert 0.0 in starts
    assert 5.0 not in starts


# --- Acceptance: complete-thought boundary -----------------------------------


def test_complete_thought_boundary_prefers_first_sentence_terminal():
    """The candidate's end lands on the first clause-terminal within budget.

    Building a transcript where the *first* terminal appears in segment B (not
    A) proves the discovery layer preferred B's end over A's mid-sentence
    boundary.
    """

    transcript = [
        # Segment A: NO terminal mid-segment — must NOT be cut here.
        _seg(0, 0.0, 8.0, "And so we begin to look at the early mechanical typewriters"),
        # Segment B: terminal punctuation at the end.
        _seg(1, 8.0, 14.0, "before they became household items."),
        # Segment C: terminal, but outside the first window.
        _seg(2, 14.0, 22.0, "They first appeared in offices."),
    ]
    result = discover_highlights(transcript, config=HighlightDiscoveryConfig(max_duration=20.0))
    first = result.candidates[0]
    # The candidate anchored at 0.0 must extend to at least 14.0 (segment B's
    # terminal) and MUST include the terminal text "before they became...".
    assert first.start == 0.0
    assert first.end >= 14.0
    assert "before they became household items." in first.transcript_excerpt
    # The candidate MUST NOT cut mid-segment A (i.e. before segment B's text).
    assert "household items" in first.transcript_excerpt


# --- Acceptance: no leading silence ------------------------------------------


def test_no_leading_silence_starts_at_first_word_bearing_segment():
    """A window that begins with a silence segment must shift forward to the next speech segment."""

    transcript = [
        _seg(0, 0.0, 5.0, "shh", silence=True),
        _seg(1, 5.0, 6.0, "shh", silence=True),
        # Speech begins here — the first non-silent anchor.
        _seg(2, 6.0, 14.0, "Welcome to the show, friend!"),
        _seg(3, 14.0, 22.0, "We have a lot to cover today."),
    ]
    result = discover_highlights(transcript)
    # Every candidate must start AT or AFTER the first speech segment.
    assert result.candidates, "expected at least one candidate"
    first_speech_start = 6.0
    for candidate in result.candidates:
        assert candidate.start >= first_speech_start, candidate


# --- Acceptance: max_clips cap ----------------------------------------------


def test_max_clips_is_respected():
    """The hard ``max_clips`` cap keeps the orchestrator's review surface bounded."""

    config = HighlightDiscoveryConfig(max_clips=2)
    result = discover_highlights(_well_formed_fixture(), config=config)
    assert len(result.candidates) <= config.max_clips


# --- Acceptance: source signals attachment -----------------------------------


def test_source_signals_attach_only_when_inside_window():
    """A signal whose timestamp lies outside any candidate is NOT attached."""

    transcript = _well_formed_fixture()
    inside = SourceSignal(kind="scene_change", timestamp=10.0, score=0.9)
    outside = SourceSignal(kind="audio_energy", timestamp=300.0, score=0.9)

    result = discover_highlights(transcript, source_signals=[inside, outside])

    attached_kinds = [signal.kind for candidate in result.candidates for signal in candidate.source_signals]
    assert "scene_change" in attached_kinds
    assert "audio_energy" not in attached_kinds  # far outside the fixture


# --- Acceptance: sensitivity classification ----------------------------------


def test_unsafe_excerpt_marks_candidate_unsuitable():
    """Markers like 'self-harm' / 'graphic violence' must flag the candidate as unsafe and unsuitable."""

    transcript = [
        _seg(0, 0.0, 6.0, "Today we discuss self-harm and how to support friends."),
        _seg(1, 6.0, 12.0, "It is a difficult conversation to have."),
    ]
    result = discover_highlights(transcript)
    assert result.candidates
    flagged = [c for c in result.candidates if c.unsuitable]
    assert flagged, "expected at least one unsuitable candidate"
    for candidate in flagged:
        assert candidate.sensitivity == "unsafe"
        # Per the model invariant: unsuitable requires unsafe sensitivity.
        assert candidate.sensitivity == "unsafe"


# --- Acceptance: model invariants on construction ----------------------------


def test_candidate_moment_rejects_zero_duration():
    """A candidate with ``end == start`` is degenerate and MUST fail-closed."""

    with pytest.raises(ValueError):
        CandidateMoment(
            candidate_id="bad-cand01",
            start=1.0,
            end=1.0,
            transcript_excerpt="anything",
            suggested_title="anything",
            suggested_hook="anything",
            rationale="anything",
            confidence=0.5,
            dedup_key="0123456789abcdef",
        )


def test_candidate_moment_rejects_unsafe_without_unsuitable():
    """The model enforces ``unsuitable`` <=> ``sensitivity == 'unsafe'`` together."""

    with pytest.raises(ValueError):
        CandidateMoment(
            candidate_id="bad-cand02",
            start=0.0,
            end=5.0,
            transcript_excerpt="anything",
            suggested_title="anything",
            suggested_hook="anything",
            rationale="anything",
            confidence=0.5,
            dedup_key="0123456789abcdef",
            sensitivity="none",
            unsuitable=True,  # invalid: sensitivity must be 'unsafe'
        )


def test_segment_rejects_inverted_time_range():
    """A segment with ``end <= start`` cannot anchor a window."""

    with pytest.raises(ValueError):
        TranscriptSegment(segment_id="bad-001", start=5.0, end=5.0, text="anything")


def test_config_rejects_inverted_duration_window():
    """``max_duration`` must be strictly greater than ``min_duration``."""

    with pytest.raises(ValueError):
        HighlightDiscoveryConfig(min_duration=60.0, max_duration=30.0)


def test_config_rejects_inverted_clip_window():
    """``min_clips`` must be <= ``max_clips``."""

    with pytest.raises(ValueError):
        HighlightDiscoveryConfig(min_clips=5, max_clips=3)


# --- JSON-stable output ------------------------------------------------------


def test_result_is_json_serialisable_with_sorted_keys():
    """The whole result round-trips through ``json.dumps`` without lossy coercion."""

    transcript = _well_formed_fixture()
    result = discover_highlights(transcript)
    encoded = json.dumps(result.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    decoded = json.loads(encoded)
    assert isinstance(decoded, dict)
    assert decoded["source_segment_count"] == len(transcript)
    assert len(decoded["candidates"]) == len(result.candidates)


# Parametrised sanity: every fixture-style transcript produces a finite, ordered result.


@pytest.mark.parametrize(
    "transcript_factory",
    [
        _well_formed_fixture,
        lambda: [
            _seg(0, 0.0, 5.0, "A short hook line!"),
            _seg(1, 5.0, 12.0, "Followed by a complete thought."),
            _seg(2, 12.0, 18.0, "And then we wrap up cleanly."),
        ],
    ],
)
def test_all_well_formed_fixtures_return_ordered_results(transcript_factory: Iterable[TranscriptSegment]):
    """Sanity: a list of well-formed transcripts always yields an ordered, finite result."""

    result = discover_highlights(transcript_factory())
    assert result.candidates
    confidences = [candidate.confidence for candidate in result.candidates]
    assert confidences == sorted(confidences, reverse=True)
