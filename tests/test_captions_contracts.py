"""Contract tests for caption timings and deterministic SRT output."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.product.captions import PhraseCue, WordTiming, build_srt_body


def _word(
    word: str = "hello",
    start: float = 0.0,
    end: float = 0.5,
    probability: float | None = None,
) -> WordTiming:
    return WordTiming(word=word, start=start, end=end, probability=probability)


def _cue(
    text: str = "hello",
    words: tuple[WordTiming, ...] | list[WordTiming] | None = None,
) -> PhraseCue:
    source_words = words if words is not None else (_word(),)
    return PhraseCue(
        start=source_words[0].start,
        end=source_words[-1].end,
        text=text,
        words=source_words,
    )


def test_word_and_nested_cue_words_are_deeply_immutable() -> None:
    source = [_word()]
    cue = _cue(words=source)
    source.append(_word("ignored", 0.5, 1.0))

    assert cue.words == (_word(),)
    assert isinstance(cue.words, tuple)
    with pytest.raises(ValidationError):
        cue.text = "changed"
    with pytest.raises(ValidationError):
        cue.words[0].word = "changed"


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-0.1, 0.5),
        (0.5, 0.5),
        (0.6, 0.5),
        (float("nan"), 0.5),
        (0.0, float("nan")),
        (float("inf"), 1.0),
        (0.0, float("inf")),
        (float("-inf"), 1.0),
    ],
)
def test_word_rejects_invalid_nonfinite_or_inverted_timing(start: float, end: float) -> None:
    with pytest.raises(ValidationError):
        _word(start=start, end=end)


@pytest.mark.parametrize("probability", [-0.01, 1.01, float("nan"), float("inf")])
def test_word_probability_is_optional_finite_and_bounded(probability: float) -> None:
    with pytest.raises(ValidationError):
        _word(probability=probability)


def test_word_preserves_unknown_probability_as_none() -> None:
    assert _word().probability is None
    assert _word(probability=0.0).probability == 0.0


@pytest.mark.parametrize("word", ["", " ", "\t\n"])
def test_word_rejects_empty_text(word: str) -> None:
    with pytest.raises(ValidationError):
        _word(word=word)


@pytest.mark.parametrize("text", ["", " ", "\t\n"])
def test_cue_rejects_empty_text(text: str) -> None:
    with pytest.raises(ValidationError):
        _cue(text=text)


def test_cue_rejects_empty_source_words() -> None:
    with pytest.raises(ValidationError):
        PhraseCue(start=0.0, end=0.5, text="hello", words=())


@pytest.mark.parametrize(
    ("start", "end"),
    [(0.1, 1.0), (0.0, 0.9)],
)
def test_cue_must_exactly_span_first_and_last_source_word(start: float, end: float) -> None:
    words = (_word("one", 0.0, 0.4), _word("two", 0.6, 1.0))
    with pytest.raises(ValidationError, match="span exactly"):
        PhraseCue(start=start, end=end, text="one two", words=words)


def test_cue_rejects_overlapping_source_words() -> None:
    words = (
        _word("one", 0.0, 0.5),
        _word("two", 0.4, 0.8),
        _word("three", 0.8, 1.0),
    )

    with pytest.raises(ValidationError, match="source words must be monotonic"):
        _cue("one two three", words)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (-0.1, 1.0),
        (1.0, 1.0),
        (2.0, 1.0),
        (float("nan"), 1.0),
        (0.0, float("inf")),
    ],
)
def test_cue_rejects_invalid_nonfinite_or_inverted_timing(start: float, end: float) -> None:
    with pytest.raises(ValidationError):
        PhraseCue(start=start, end=end, text="hello", words=(_word(),))


def test_build_srt_body_formats_bounded_monotonic_cues_with_canonical_timestamps() -> None:
    first = _cue("Hello", [_word("Hello", 0.0, 1.9999, 0.8)])
    second = _cue("world", [_word("world", 1.9999, 3661.125, 1.0)])

    assert build_srt_body((first, second)) == (
        "1\n00:00:00,000 --> 00:00:01,999\nHello\n\n2\n00:00:01,999 --> 01:01:01,125\nworld\n"
    )


def test_build_srt_body_allows_cues_that_touch_without_overlapping() -> None:
    first = _cue("one", [_word("one", 0.0, 1.0)])
    second = _cue("two", [_word("two", 1.0, 2.0)])

    assert "\n\n2\n00:00:01,000 -->" in build_srt_body((first, second))


@pytest.mark.parametrize("second_start", [0.5, 0.0])
def test_build_srt_body_rejects_overlapping_or_non_monotonic_cues(second_start: float) -> None:
    first = _cue("one", [_word("one", 0.0, 1.0)])
    second = _cue("two", [_word("two", second_start, 2.0)])

    with pytest.raises(ValueError, match="monotonic and non-overlapping"):
        build_srt_body((first, second))


def test_build_srt_body_is_byte_deterministic_and_empty_safe() -> None:
    cues = (_cue("repeat", [_word("repeat", 0.125, 0.875)]),)

    first = build_srt_body(cues).encode("utf-8")
    second = build_srt_body(cues).encode("utf-8")
    assert first == second
    assert build_srt_body(()) == ""
