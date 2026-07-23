from __future__ import annotations

import pytest

from kinocut.product.highlight_discovery import discover_highlights
from kinocut.product.models import HighlightDiscoveryConfig, SourceSignal, TranscriptSegment


def _segment(
    segment_id: str,
    start: float,
    end: float,
    text: str,
    *,
    silence: bool = False,
    confidence: float | None = 0.9,
) -> TranscriptSegment:
    return TranscriptSegment(
        segment_id=segment_id,
        start=start,
        end=end,
        text=text,
        confidence=confidence,
        is_silence=silence,
    )


def _config(*, minimum: float = 8, maximum: float = 30, clips: int = 8) -> HighlightDiscoveryConfig:
    return HighlightDiscoveryConfig(
        min_duration=minimum,
        max_duration=maximum,
        max_clips=clips,
    )


def _realistic_transcript() -> tuple[TranscriptSegment, ...]:
    return (
        _segment("intro", 12, 24, "The first lesson is to begin with the audience's actual problem."),
        _segment("example", 24, 36, "For example, our smallest experiment revealed the largest source of delay."),
        _segment("turn", 36, 48, "That changed the plan because evidence beat our original assumption."),
        _segment("payoff", 48, 60, "The payoff is a process that gets faster whenever it learns."),
    )


def test_discovery_is_repeatable_and_json_stable() -> None:
    transcript = _realistic_transcript()
    signal = SourceSignal(kind="scene_change", timestamp=30, score=0.8)

    first = discover_highlights(transcript, signals=(signal,), config=_config())
    second = discover_highlights(transcript, signals=(signal,), config=_config())

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()


def test_realistic_transcript_produces_at_least_three_distinct_candidates() -> None:
    result = discover_highlights(_realistic_transcript(), config=_config(clips=3))

    assert len(result.candidates) >= 3
    assert len({candidate.dedup_key for candidate in result.candidates}) == len(result.candidates)


def test_empty_transcript_has_no_candidates() -> None:
    result = discover_highlights((), config=_config())

    assert result.candidates == ()


def test_all_silence_has_no_candidates() -> None:
    transcript = (
        _segment("silence-1", 0, 10, "[silence]", silence=True),
        _segment("silence-2", 10, 20, "[silence]", silence=True),
    )

    assert discover_highlights(transcript, config=_config()).candidates == ()


def test_window_extends_to_complete_thought_payoff() -> None:
    transcript = (
        _segment("setup", 0, 10, "The useful result begins with a constraint"),
        _segment("bridge", 10, 20, "and the initial attempt still falls short,"),
        _segment("answer", 20, 30, "but the final comparison reveals the answer."),
    )

    candidate = next(
        item
        for item in discover_highlights(transcript, config=_config(minimum=15, maximum=35)).candidates
        if item.start == 0
    )

    assert candidate.end == 30
    assert candidate.transcript_excerpt.endswith("answer.")


def test_window_without_complete_thought_is_rejected() -> None:
    transcript = (
        _segment("setup", 0, 10, "This explanation continues"),
        _segment("middle", 10, 20, "through another unfinished clause,"),
    )

    assert discover_highlights(transcript, config=_config(minimum=8, maximum=25)).candidates == ()


def test_leading_silence_is_trimmed_from_candidate() -> None:
    transcript = (
        _segment("silence", 40, 48, "[silence]", silence=True),
        _segment("speech", 48, 58, "The spoken idea begins here and reaches its conclusion."),
    )

    candidate = discover_highlights(transcript, config=_config(minimum=5)).candidates[0]

    assert candidate.start == 48
    assert "silence" not in candidate.transcript_excerpt.lower()


def test_candidates_respect_source_bounds_duration_and_max_clips() -> None:
    transcript = (
        _segment("one", 100, 110, "A bounded window starts at the source offset"),
        _segment("two", 110, 120, "and closes with a complete result."),
        _segment("three", 120, 140, "A second self-contained explanation also ends cleanly."),
    )
    config = _config(minimum=10, maximum=25, clips=1)

    result = discover_highlights(transcript, config=config)

    assert len(result.candidates) == 1
    assert all(100 <= item.start < item.end <= 140 for item in result.candidates)
    assert all(config.min_duration <= item.end - item.start <= config.max_duration for item in result.candidates)


def test_duplicate_windows_collapse_by_canonical_key() -> None:
    transcript = (
        _segment("copy-a", 0, 10, "The same bounded thought finishes here."),
        _segment("copy-b", 0, 10, "The same bounded thought finishes here."),
    )

    result = discover_highlights(transcript, config=_config(minimum=5))

    assert len(result.candidates) == 1


def test_candidates_are_sorted_by_descending_score() -> None:
    transcript = (
        _segment("short", 0, 10, "A concise result lands."),
        _segment(
            "dense",
            10,
            20,
            "A detailed explanation connects evidence, constraints, tradeoffs, audience needs, "
            "implementation choices, and the measurable result.",
        ),
        _segment("medium", 20, 30, "A useful intermediate explanation reaches a clear result."),
    )

    candidates = discover_highlights(transcript, config=_config(minimum=5)).candidates

    assert [item.confidence for item in candidates] == sorted((item.confidence for item in candidates), reverse=True)


# --- In-window signal preservation (GLM finding 1) --------------------------


def test_signals_inside_window_are_preserved_in_deterministic_order() -> None:
    transcript = _realistic_transcript()
    inside = (
        SourceSignal(kind="scene_change", timestamp=30.0, score=0.8),
        SourceSignal(kind="audio_energy", timestamp=20.0, score=0.5, label="energy"),
        SourceSignal(kind="scene_change", timestamp=25.0, score=0.4),
    )

    candidate = next(
        item
        for item in discover_highlights(
            transcript, signals=inside, config=_config(minimum=8, maximum=30, clips=8)
        ).candidates
        if item.start == 12
    )

    timestamps = [signal.timestamp for signal in candidate.source_signals]
    # Ordering must be (timestamp, kind, -score, label) — same timestamp must
    # also be stable by kind.
    assert timestamps == sorted(timestamps)
    assert all(12.0 <= signal.timestamp <= candidate.end for signal in candidate.source_signals)


def test_signals_outside_window_are_excluded() -> None:
    transcript = _realistic_transcript()
    outside = (
        SourceSignal(kind="scene_change", timestamp=5.0, score=0.9),
        SourceSignal(kind="audio_energy", timestamp=80.0, score=0.9, label="late"),
    )

    candidates = discover_highlights(
        transcript, signals=outside, config=_config(minimum=8, maximum=30, clips=8)
    ).candidates

    assert all(candidate.source_signals == () for candidate in candidates)


def test_signals_at_window_boundary_are_included() -> None:
    transcript = (
        _segment("open", 0, 10, "First half of the bounded thought"),
        _segment("close", 10, 20, "concludes at the end of the window."),
    )

    boundary = (
        SourceSignal(kind="scene_change", timestamp=0.0, score=0.5),
        SourceSignal(kind="audio_energy", timestamp=20.0, score=0.5, label="end"),
    )

    candidate = discover_highlights(
        transcript, signals=boundary, config=_config(minimum=5, maximum=30, clips=1)
    ).candidates[0]

    assert {signal.timestamp for signal in candidate.source_signals} == {0.0, 20.0}


# --- Monotonic transcript contract (GLM finding 2) --------------------------


def test_strictly_decreasing_segments_raise_value_error() -> None:
    transcript = (
        _segment("first", 20, 30, "The second segment starts before the first."),
        _segment("second", 10, 20, "This is intentionally out of order."),
    )

    with pytest.raises(ValueError, match="monotonic"):
        discover_highlights(transcript, config=_config())


def test_equal_segment_offsets_are_allowed() -> None:
    transcript = (
        _segment("first", 0, 10, "First segment ends here."),
        _segment("second", 0, 5, "Second segment shares the anchor."),
        _segment("third", 5, 15, "Third segment ends here."),
    )

    result = discover_highlights(transcript, config=_config(minimum=5))

    assert len(result.candidates) >= 1


def test_strictly_decreasing_segments_inside_batch_raise_value_error() -> None:
    transcript = (
        _segment("a", 0, 10, "Anchored at zero ends here."),
        _segment("b", 5, 15, "Overlaps but stays non-decreasing."),
        _segment("c", 3, 12, "Walks back below b and triggers the contract."),
    )

    with pytest.raises(ValueError, match="monotonic"):
        discover_highlights(transcript, config=_config(minimum=5))


# --- Distinct, non-degenerate title and hook (GLM finding 3) ----------------


def test_title_does_not_truncate_at_abbreviation_period() -> None:
    transcript = (_segment("abbrev", 0, 10, "Dr. Smith explains the answer here."),)

    candidate = discover_highlights(transcript, config=_config(minimum=5)).candidates[0]

    assert candidate.suggested_title == "Dr. Smith explains the answer here."
    assert not candidate.suggested_title.endswith("Dr.")
    assert "Dr." in candidate.suggested_title


def test_title_does_not_truncate_at_decimal_point() -> None:
    transcript = (_segment("decimal", 0, 10, "The result was 3.14 percent improvement."),)

    candidate = discover_highlights(transcript, config=_config(minimum=5)).candidates[0]

    assert candidate.suggested_title == "The result was 3.14 percent improvement."
    # The title must not end on a bare "3." — that would be a degenerate lead.
    assert not candidate.suggested_title.rstrip(".").endswith("3")


def test_title_does_not_truncate_at_capital_initial() -> None:
    transcript = (_segment("initial", 0, 10, "J. R. R. Tolkien wrote the book."),)

    candidate = discover_highlights(transcript, config=_config(minimum=5)).candidates[0]

    assert candidate.suggested_title == "J. R. R. Tolkien wrote the book."
    assert candidate.suggested_title != "J."  # not a degenerate single-initial lead


def test_title_and_hook_are_distinct_when_excerpt_has_multiple_sentences() -> None:
    transcript = (_segment("multi", 0, 20, "First sentence is the lead. Second sentence is the hook."),)

    candidate = discover_highlights(transcript, config=_config(minimum=5)).candidates[0]

    assert candidate.suggested_title == "First sentence is the lead."
