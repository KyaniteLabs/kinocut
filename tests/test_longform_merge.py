from __future__ import annotations

from copy import deepcopy
import math

import pytest

from kinocut.ai_engine._longform_merge import (
    _build_dedup_tail,
    _extract_segment_words,
    _merge_chunk,
    _segment_avg_logprob,
    _segment_no_speech_prob,
    _word_probability,
)
from kinocut.ai_engine._longform_models import LongformChunk, LongformSegment, LongformWord


def _chunk(index: int, start: float, end: float) -> LongformChunk:
    return LongformChunk(index=index, start=start, end=end, duration=end - start)


def _segment(
    text: str,
    start: float,
    end: float,
    words: list[dict] | None = None,
    **extra,
) -> dict:
    return {"text": text, "start": start, "end": end, "words": words or [], **extra}


@pytest.mark.parametrize(
    "word,expected",
    [
        ({"probability": 0.7, "avg_logprob": -10}, 0.7),
        ({"avg_logprob": math.log(0.4)}, 0.4),
        ({"avg_logprob": 1.0}, 1.0),
        ({}, None),
        ({"probability": "bad"}, None),
        ({"probability": float("nan")}, None),
    ],
)
def test_word_probability_is_truthful(word, expected) -> None:
    actual = _word_probability(word)
    if expected is None:
        assert actual is None
    else:
        assert actual == pytest.approx(expected)


@pytest.mark.parametrize(
    "value,expected",
    [(0.2, 0.2), (None, None), ("bad", None), (-0.1, None), (1.1, None), (float("nan"), None)],
)
def test_segment_no_speech_probability_is_bounded(value, expected) -> None:
    assert _segment_no_speech_prob({"no_speech_prob": value}) == expected


@pytest.mark.parametrize(
    "value,expected",
    [(-0.2, -0.2), (0.0, 0.0), (None, None), ("bad", None), (0.1, None), (float("nan"), None), (float("inf"), None)],
)
def test_segment_avg_logprob_is_finite_and_non_positive(value, expected) -> None:
    assert _segment_avg_logprob({"avg_logprob": value}) == expected


def test_extract_segment_words_preserves_timings_and_unknown_confidence() -> None:
    segment = _segment(
        "hello world",
        0,
        2,
        [
            {"word": " hello ", "start": 0.1, "end": 0.6, "probability": 0.8},
            {"word": "world", "start": 1.2, "end": 1.8},
            {"word": "", "start": 0, "end": 1},
            {"word": "zero", "start": 1, "end": 1},
        ],
    )
    assert _extract_segment_words(segment) == [
        ("hello", 0.1, 0.6, 0.8),
        ("world", 1.2, 1.8, None),
    ]


def test_extract_segment_words_skips_non_mapping_entries() -> None:
    assert _extract_segment_words({"words": [None, "bad", 1]}) == []


def test_build_dedup_tail_uses_casefolded_overlap_words() -> None:
    words = [
        LongformWord(word="Before", start=4, end=5, chunk_index=0),
        LongformWord(word=" Again ", start=5, end=6, chunk_index=0),
    ]
    assert _build_dedup_tail(words, 5) == {"again"}


def test_merge_remaps_global_time_dedups_overlap_and_keeps_unique_words() -> None:
    words = [LongformWord(word="Again", start=5.2, end=5.7, chunk_index=0, probability=0.9)]
    segments: list[LongformSegment] = []
    raw = {
        "segments": [
            _segment(
                "again now",
                0,
                2,
                [
                    {"word": " again ", "start": 0.2, "end": 0.7, "probability": 0.4},
                    {"word": "now", "start": 1.0, "end": 1.5},
                ],
                avg_logprob=-0.3,
                no_speech_prob=0.1,
            )
        ]
    }
    before = deepcopy(raw)
    _merge_chunk(words, segments, raw, _chunk(1, 5, 10), overlap_seconds=2, prev_chunk_end=7)
    assert [word.word for word in words] == ["Again", "now"]
    assert words[-1].start == 6.0
    assert words[-1].end == 6.5
    assert words[-1].probability is None
    assert segments[0].start == 5
    assert segments[0].end == 7
    assert segments[0].avg_logprob == -0.3
    assert segments[0].no_speech_prob == 0.1
    assert raw == before


def test_merge_keeps_unique_word_inside_overlap_tail() -> None:
    words = [LongformWord(word="old", start=9, end=9.5, chunk_index=0)]
    segments: list[LongformSegment] = []
    raw = {"segments": [_segment("new", 0.2, 1, [{"word": "new", "start": 0.2, "end": 0.8}])]}
    _merge_chunk(words, segments, raw, _chunk(1, 9, 15), overlap_seconds=2, prev_chunk_end=11)
    assert [word.word for word in words] == ["old", "new"]
    assert words[-1].start == pytest.approx(9.2)


def test_merge_segment_without_words_retains_truthful_metadata() -> None:
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    raw = {"segments": [_segment("spoken", 1, 2, avg_logprob=-0.5)]}
    _merge_chunk(words, segments, raw, _chunk(0, 10, 20), overlap_seconds=2, prev_chunk_end=None)
    assert words == []
    assert segments == [
        LongformSegment(
            start=11,
            end=12,
            text="spoken",
            chunk_index=0,
            avg_logprob=-0.5,
            no_speech_prob=None,
        )
    ]


def test_merge_skips_invalid_empty_or_zero_width_segments() -> None:
    words: list[LongformWord] = []
    segments: list[LongformSegment] = []
    raw = {
        "segments": [
            None,
            "bad",
            _segment("", 0, 1),
            _segment("zero", 1, 1),
            {"text": "bad", "start": "x"},
            _segment("metadata", 2, 3, avg_logprob=float("nan")),
        ]
    }
    _merge_chunk(words, segments, raw, _chunk(0, 0, 10), overlap_seconds=2, prev_chunk_end=None)
    assert words == []
    assert segments == [
        LongformSegment(
            start=2,
            end=3,
            text="metadata",
            chunk_index=0,
            avg_logprob=None,
            no_speech_prob=None,
        )
    ]
