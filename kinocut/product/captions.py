"""Strict caption timing contracts and deterministic SRT serialization."""

from __future__ import annotations

from collections.abc import Sequence
from itertools import pairwise

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


__all__ = ["PhraseCue", "WordTiming", "build_srt_body"]
