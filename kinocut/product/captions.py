"""Strict caption timing contracts and deterministic SRT serialization."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from itertools import pairwise
from typing import Any, Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.ffmpeg_helpers import _seconds_to_srt_time


class WordTiming(ValueObject):
    """One source word with a finite, positive-duration time range."""

    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _validate_timing(self) -> WordTiming:
        if not self.word.strip():
            raise ValueError("word must contain non-whitespace text")
        if self.end <= self.start:
            raise ValueError("word end must be strictly greater than start")
        return self


class PhraseCue(ValueObject):
    """A visible cue bound exactly to its immutable source-word span."""

    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str = Field(min_length=1)
    words: tuple[WordTiming, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_cue(self) -> PhraseCue:
        if not self.text.strip():
            raise ValueError("cue text must contain non-whitespace text")
        if self.end <= self.start:
            raise ValueError("cue end must be strictly greater than start")
        if self.start != self.words[0].start or self.end != self.words[-1].end:
            raise ValueError("cue must span exactly its first and last source word")
        if any(current.start < previous.end for previous, current in pairwise(self.words)):
            raise ValueError("cue source words must be monotonic and non-overlapping")
        return self


LowConfidencePolicy = Literal["omit", "flag"]


class CaptionConfig(ValueObject):
    """Immutable, bounded phrase-grouping policy."""

    max_words_per_cue: int = Field(default=8, ge=1, le=100)
    max_cue_duration: float = Field(default=4.0, gt=0.0, le=60.0)
    low_confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    on_low_confidence: LowConfidencePolicy = "flag"


class CaptionArtifact(ValueObject):
    """Editable phrase cues and their deterministic SRT serialization."""

    cues: tuple[PhraseCue, ...]
    srt_body: str
    warnings: tuple[str, ...]
    low_confidence_token_count: int = Field(ge=0)
    omitted_token_count: int = Field(ge=0)


def build_srt_body(cues: Sequence[PhraseCue]) -> str:
    """Serialize ordered, non-overlapping cues into a stable SRT body."""

    blocks: list[str] = []
    previous_end: float | None = None
    for number, cue in enumerate(cues, start=1):
        if previous_end is not None and cue.start < previous_end:
            raise ValueError("caption cues must be monotonic and non-overlapping")
        blocks.append(f"{number}\n{_seconds_to_srt_time(cue.start)} --> {_seconds_to_srt_time(cue.end)}\n{cue.text}")
        previous_end = cue.end
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def build_caption_artifact(
    words: Iterable[WordTiming | Mapping[str, Any]],
    *,
    config: CaptionConfig | None = None,
) -> CaptionArtifact:
    """Build truthful phrase cues without changing any source timestamp."""

    cfg = config or CaptionConfig()
    normalized = sorted((_coerce_word(item) for item in words), key=lambda word: word.start)
    for previous, current in pairwise(normalized):
        if current.start < previous.end:
            raise ValueError("caption words must be unambiguously ordered and non-overlapping")

    groups: list[list[WordTiming]] = []
    current_group: list[WordTiming] = []
    for word in normalized:
        if word.end - word.start > cfg.max_cue_duration:
            raise ValueError("a source word exceeds max_cue_duration and cannot be split truthfully")
        exceeds_limit = current_group and (
            len(current_group) >= cfg.max_words_per_cue or word.end - current_group[0].start > cfg.max_cue_duration
        )
        if exceeds_limit:
            groups.append(current_group)
            current_group = []
        current_group.append(word)
        if _is_clause_terminal(word.word):
            groups.append(current_group)
            current_group = []
    if current_group:
        groups.append(current_group)

    cues: list[PhraseCue] = []
    warnings: list[str] = []
    low_confidence_count = 0
    omitted_count = 0
    for group in groups:
        visible_tokens: list[str] = []
        for word in group:
            is_low_confidence = word.probability is not None and word.probability < cfg.low_confidence_threshold
            if not is_low_confidence:
                visible_tokens.append(word.word)
                continue
            low_confidence_count += 1
            if cfg.on_low_confidence == "flag":
                visible_tokens.append("[?]")
            else:
                omitted_count += 1
        text = " ".join(visible_tokens).strip()
        if not text:
            if "empty_visible_cue_dropped" not in warnings:
                warnings.append("empty_visible_cue_dropped")
            continue
        cues.append(
            PhraseCue(
                start=group[0].start,
                end=group[-1].end,
                text=text,
                words=tuple(group),
            )
        )

    if low_confidence_count:
        action = "omitted" if cfg.on_low_confidence == "omit" else "flagged"
        warnings.insert(0, f"low_confidence_tokens_{action}")
    cue_tuple = tuple(cues)
    return CaptionArtifact(
        cues=cue_tuple,
        srt_body=build_srt_body(cue_tuple),
        warnings=tuple(warnings),
        low_confidence_token_count=low_confidence_count,
        omitted_token_count=omitted_count,
    )


def _coerce_word(item: WordTiming | Mapping[str, Any]) -> WordTiming:
    if isinstance(item, WordTiming):
        return item
    if isinstance(item, Mapping):
        return WordTiming.model_validate(item)
    raise TypeError(f"expected WordTiming or mapping, got {type(item).__name__}")


def _is_clause_terminal(text: str) -> bool:
    return text.rstrip().rstrip("\"')]").endswith((".", "!", "?"))


__all__ = [
    "CaptionArtifact",
    "CaptionConfig",
    "LowConfidencePolicy",
    "PhraseCue",
    "WordTiming",
    "build_caption_artifact",
    "build_srt_body",
]
