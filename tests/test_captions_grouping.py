"""Behavior tests for deterministic phrase-level caption artifacts."""

from __future__ import annotations

import re

import pytest
from pydantic import ValidationError

from kinocut.product.captions import CaptionConfig, WordTiming, build_caption_artifact


def _word(
    text: str,
    start: float,
    end: float,
    probability: float | None = None,
) -> WordTiming:
    return WordTiming(word=text, start=start, end=end, probability=probability)


def test_groups_words_into_editable_phrase_cues() -> None:
    words = [_word("Hello", 0.1, 0.4), _word("there", 0.5, 0.9)]

    artifact = build_caption_artifact(words)

    assert artifact.cues[0].text == "Hello there"
    assert artifact.cues[0].words == tuple(words)
    assert artifact.srt_body.endswith("Hello there\n")


def test_clause_terminal_punctuation_closes_phrase() -> None:
    words = [_word("One.", 0.0, 0.4), _word("Two", 0.5, 0.9), _word("three?", 1.0, 1.4)]

    artifact = build_caption_artifact(words)

    assert [cue.text for cue in artifact.cues] == ["One.", "Two three?"]


def test_word_and_duration_bounds_split_without_changing_times() -> None:
    config = CaptionConfig(max_words_per_cue=2, max_cue_duration=1.0)
    words = [
        _word("a", 0.0, 0.2),
        _word("b", 0.3, 0.5),
        _word("c", 0.6, 0.8),
        _word("d", 1.5, 1.8),
    ]

    artifact = build_caption_artifact(words, config=config)

    assert [(cue.start, cue.end, cue.text) for cue in artifact.cues] == [
        (0.0, 0.5, "a b"),
        (0.6, 0.8, "c"),
        (1.5, 1.8, "d"),
    ]


def test_srt_is_parseable_and_monotonic() -> None:
    artifact = build_caption_artifact([_word("First.", 0.125, 0.875), _word("Second.", 1.0, 1.75)])
    blocks = artifact.srt_body.strip().split("\n\n")
    timestamp = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$")

    assert [block.splitlines()[0] for block in blocks] == ["1", "2"]
    assert all(timestamp.fullmatch(block.splitlines()[1]) for block in blocks)
    assert blocks[0].splitlines()[1].split(" --> ")[1] <= blocks[1].splitlines()[1].split(" --> ")[0]


def test_mapping_input_is_coerced_to_word_timing() -> None:
    artifact = build_caption_artifact([{"word": "mapped", "start": 0.0, "end": 0.4, "probability": 0.8}])

    assert artifact.cues[0].words == (_word("mapped", 0.0, 0.4, 0.8),)


def test_low_confidence_flag_is_canonical_and_metadata_is_truthful() -> None:
    source = _word("uncertain", 0.0, 0.4, 0.2)
    artifact = build_caption_artifact(
        [source],
        config=CaptionConfig(low_confidence_threshold=0.5, on_low_confidence="flag"),
    )

    assert artifact.cues[0].text == "[?]"
    assert artifact.cues[0].words == (source,)
    assert artifact.low_confidence_token_count == 1
    assert artifact.omitted_token_count == 0


def test_low_confidence_omit_retains_metadata_and_counts() -> None:
    hidden = _word("uncertain", 0.4, 0.8, 0.2)
    artifact = build_caption_artifact(
        [_word("keep", 0.0, 0.3, 0.9), hidden],
        config=CaptionConfig(low_confidence_threshold=0.5, on_low_confidence="omit"),
    )

    assert artifact.cues[0].text == "keep"
    assert artifact.cues[0].words[1] == hidden
    assert artifact.low_confidence_token_count == 1
    assert artifact.omitted_token_count == 1


def test_empty_visible_cue_is_dropped_with_warning() -> None:
    artifact = build_caption_artifact(
        [_word("hidden.", 0.0, 0.4, 0.1)],
        config=CaptionConfig(on_low_confidence="omit"),
    )

    assert artifact.cues == ()
    assert artifact.srt_body == ""
    assert "empty_visible_cue_dropped" in artifact.warnings
    assert artifact.omitted_token_count == 1


def test_unknown_confidence_is_preserved_and_visible() -> None:
    artifact = build_caption_artifact([_word("unknown", 0.0, 0.4)])

    assert artifact.cues[0].text == "unknown"
    assert artifact.cues[0].words[0].probability is None
    assert artifact.low_confidence_token_count == 0


def test_empty_input_returns_empty_editable_artifact() -> None:
    artifact = build_caption_artifact([])

    assert artifact.cues == ()
    assert artifact.srt_body == ""
    assert artifact.warnings == ()


def test_ambiguous_overlap_is_rejected_after_sorting() -> None:
    words = [_word("later", 0.4, 0.8), _word("earlier", 0.0, 0.5)]

    with pytest.raises(ValueError, match="unambiguously ordered"):
        build_caption_artifact(words)


def test_non_overlapping_input_is_sorted_deterministically() -> None:
    words = [_word("second", 0.5, 0.9), _word("first", 0.0, 0.4)]

    first = build_caption_artifact(words)
    second = build_caption_artifact(words)

    assert first == second
    assert first.cues[0].text == "first second"


def test_no_cumulative_timing_drift_over_sixty_seconds() -> None:
    words = [_word(f"w{index}", index / 10, (index + 1) / 10) for index in range(600)]

    artifact = build_caption_artifact(words)
    flattened = [word for cue in artifact.cues for word in cue.words]

    assert flattened == words
    assert artifact.cues[0].start == words[0].start
    assert artifact.cues[-1].end == words[-1].end == 60.0


@pytest.mark.parametrize(
    "values",
    [
        {"max_words_per_cue": 0},
        {"max_cue_duration": float("inf")},
        {"low_confidence_threshold": float("nan")},
        {"on_low_confidence": "replace"},
    ],
)
def test_config_is_bounded_and_closed(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CaptionConfig(**values)
