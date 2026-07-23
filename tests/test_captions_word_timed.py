"""Behavior tests for the truthful low-confidence warning contract (issue #420)."""

from __future__ import annotations

from kinocut.product.captions import (
    CaptionConfig,
    WordTiming,
    build_caption_artifact,
)


def _word(text: str, start: float, end: float, probability: float | None) -> WordTiming:
    return WordTiming(word=text, start=start, end=end, probability=probability)


def test_all_confident_words_emit_no_low_confidence_warning() -> None:
    words = [
        _word("hello", 0.0, 0.5, 0.99),
        _word("world", 0.5, 1.0, 0.95),
    ]

    artifact = build_caption_artifact(words)

    assert artifact.low_confidence_token_count == 0
    assert artifact.omitted_token_count == 0
    assert artifact.warnings == ()


def test_flag_policy_marks_flagged_warning_when_a_token_is_below_threshold() -> None:
    words = [
        _word("hello", 0.0, 0.5, 0.99),
        _word("world", 0.5, 1.0, 0.2),
    ]

    artifact = build_caption_artifact(
        words,
        config=CaptionConfig(on_low_confidence="flag"),
    )

    assert artifact.low_confidence_token_count == 1
    assert artifact.omitted_token_count == 0
    assert artifact.warnings == ("low_confidence_tokens_flagged",)
    assert any("[?]" in cue.text for cue in artifact.cues)
