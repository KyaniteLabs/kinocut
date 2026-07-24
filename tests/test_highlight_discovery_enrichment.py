from __future__ import annotations

from kinocut.product.highlight_discovery import discover_highlights
from kinocut.product.models import HighlightDiscoveryConfig, SourceSignal, TranscriptSegment


def _segment(segment_id: str, start: float, text: str) -> TranscriptSegment:
    return TranscriptSegment(segment_id=segment_id, start=start, end=start + 10, text=text)


def _config(*, clips: int = 8, signal_weight: float = 0.25) -> HighlightDiscoveryConfig:
    return HighlightDiscoveryConfig(
        min_duration=5,
        max_duration=15,
        max_clips=clips,
        signal_weight=signal_weight,
    )


def _candidate(
    transcript: tuple[TranscriptSegment, ...],
    *,
    start: float,
    signals: tuple[SourceSignal, ...] = (),
    config: HighlightDiscoveryConfig | None = None,
):
    return next(
        item
        for item in discover_highlights(transcript, signals=signals, config=config or _config()).candidates
        if item.start == start
    )


def test_context_is_the_immediately_adjacent_transcript() -> None:
    transcript = (
        _segment("before", 0, "The discussion starts here."),
        _segment("focus", 10, "The central finding is concise and complete."),
        _segment("after", 20, "The discussion continues here."),
    )

    candidate = _candidate(transcript, start=10)

    assert candidate.context_before == transcript[0].text
    assert candidate.context_after == transcript[2].text


def test_context_at_source_edges_is_absent() -> None:
    transcript = (
        _segment("first", 0, "The first bounded idea is complete."),
        _segment("last", 10, "The last bounded idea is complete."),
    )

    assert _candidate(transcript, start=0).context_before is None
    assert _candidate(transcript, start=10).context_after is None


def test_editorial_copy_only_uses_excerpt_words() -> None:
    transcript = (
        _segment(
            "focus",
            0,
            "Careful editors preserve every original phrase while choosing a concise opening for viewers today.",
        ),
    )
    candidate = _candidate(transcript, start=0)
    excerpt_words = set(candidate.transcript_excerpt.split())

    assert set(candidate.suggested_title.split()) <= excerpt_words
    assert set(candidate.suggested_hook.split()) <= excerpt_words


def test_only_in_window_signals_blend_confidence() -> None:
    transcript = (_segment("focus", 10, "A short but complete finding lands clearly."),)
    inside = SourceSignal(kind="audio_energy", timestamp=15, score=1.0)
    outside = SourceSignal(kind="audio_energy", timestamp=30, score=1.0)
    baseline = _candidate(transcript, start=10)

    enriched = _candidate(transcript, start=10, signals=(outside, inside), config=_config(signal_weight=0.5))
    unchanged = _candidate(transcript, start=10, signals=(outside,), config=_config(signal_weight=0.5))

    assert enriched.source_signals == (inside,)
    assert enriched.confidence == round(0.5 * baseline.confidence + 0.5, 4)
    assert unchanged.confidence == baseline.confidence


def test_unsafe_term_blocks_candidate_with_stable_warning() -> None:
    transcript = (_segment("risk", 0, "The report discusses suicide prevention and support."),)

    first = _candidate(transcript, start=0)
    second = _candidate(transcript, start=0)

    assert first.sensitivity == "unsafe"
    assert first.unsuitable is True
    assert first.review_warning == "Unsafe or sensitive transcript terms require editorial review."
    assert second.review_warning == first.review_warning


def test_duplicate_window_keeps_stable_identity_and_dedup() -> None:
    transcript = (
        _segment("copy-a", 0, "The same complete result appears here."),
        _segment("copy-b", 0, "The same complete result appears here."),
    )

    first = discover_highlights(transcript, config=_config())
    second = discover_highlights(transcript, config=_config())

    assert len(first.candidates) == 1
    assert first.candidates[0].dedup_key == second.candidates[0].dedup_key
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id


def test_core_duration_ordering_and_cap_are_preserved() -> None:
    transcript = (
        _segment("one", 0, "A compact complete thought lands."),
        _segment("two", 10, "A much more detailed complete thought offers evidence and a useful conclusion."),
        _segment("three", 20, "Another complete thought lands."),
    )
    result = discover_highlights(transcript, config=_config(clips=2))

    assert len(result.candidates) == 2
    assert all(5 <= item.end - item.start <= 15 for item in result.candidates)
    assert [item.confidence for item in result.candidates] == sorted(
        (item.confidence for item in result.candidates), reverse=True
    )
