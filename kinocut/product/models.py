"""Strict product-domain models for the long-form stream-to-shorts workflow.

Models here are the public contract for moment discovery and ShortsPlan
composition. They are strict (no extra fields, frozen, no NaN), JSON-stable
(round-trip via ``model_dump(mode="json")`` with ``dedup_key`` as a stable
sha256 prefix), and decoupled from engines — value objects consumed by
``kinocut.product.shorts``/``kinocut.workflow.executor``, never the reverse.

Product-local conventions:

* Quantisation to whole-millisecond integers when computing ``dedup_key`` so
  deterministic re-runs collapse sub-millisecond float drift.
* One-directional ``unsuitable`` ⇒ ``sensitivity == "unsafe"`` semantics:
  ``unsafe`` may stand alone, but ``unsuitable`` must escalate.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import ValueObject

# Caller-owned segment identifier (permissive; producer owns the scheme).
_SEGMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

# 16-hex sha256 prefix over (start_ms, end_ms, excerpt, sensitivity).
_DEDUP_KEY_PATTERN = r"^[0-9a-f]{16}$"

# Ordinal progression; ``unsafe`` is a hard render block.
SensitivityLevel = Literal["none", "mild", "strong", "unsafe"]


# --- Inputs ------------------------------------------------------------------


class TranscriptSegment(ValueObject):
    """One timed span of transcript text."""

    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str = Field(min_length=1)
    speaker: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_silence: bool = False

    @model_validator(mode="after")
    def _validate_time_range(self) -> TranscriptSegment:
        if self.end <= self.start:
            raise ValueError("transcript segment end must be strictly greater than start")
        return self


class TranscriptWord(ValueObject):
    """One timed word/token from the long-form transcription slice."""

    word: str = Field(min_length=1)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    probability: float | None = Field(default=None, ge=0.0, le=1.0)
    chunk_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_time_range(self) -> TranscriptWord:
        if self.end <= self.start:
            raise ValueError("transcript word end must be strictly greater than start")
        return self


class SourceSignal(ValueObject):
    """One optional evidence signal attached to a candidate.

    ``kind`` is a closed literal so future additions are fail-closed.
    """

    kind: Literal["scene_change", "audio_energy"]
    timestamp: float = Field(ge=0.0)
    score: float = Field(ge=0.0, le=1.0)
    label: str | None = Field(default=None, min_length=1)


# --- Output ------------------------------------------------------------------


class CandidateMoment(ValueObject):
    """One proposed clip derived from the transcript.

    A candidate is a *suggestion*, not an executable plan. ``dedup_key`` MUST
    equal ``canonical_dedup_key(start, end, transcript_excerpt, sensitivity)``
    — the validator re-derives it so callers cannot smuggle a stale key.
    """

    candidate_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    transcript_excerpt: str = Field(min_length=1)
    suggested_title: str = Field(min_length=1)
    suggested_hook: str = Field(min_length=1)
    rationale: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    review_warning: str | None = None
    context_before: str | None = None
    context_after: str | None = None
    dedup_key: str = Field(pattern=_DEDUP_KEY_PATTERN)
    sensitivity: SensitivityLevel = "none"
    unsuitable: bool = False
    source_signals: tuple[SourceSignal, ...] = ()

    @model_validator(mode="after")
    def _validate_invariants(self) -> CandidateMoment:
        if self.end <= self.start:
            raise ValueError("candidate end must be strictly greater than start")
        if self.unsuitable and self.sensitivity != "unsafe":
            raise ValueError("unsuitable candidates must declare sensitivity='unsafe'")
        if self.dedup_key != canonical_dedup_key(
            start=self.start,
            end=self.end,
            excerpt=self.transcript_excerpt,
            sensitivity=self.sensitivity,
        ):
            raise ValueError("dedup_key does not match canonical_dedup_key(start, end, excerpt, sensitivity)")
        return self


class HighlightDiscoveryConfig(ValueObject):
    """Tunable knobs for :func:`discover_highlights`.

    ``min_clips`` is a target; ``max_clips`` is a hard cap. When the operator
    only sets ``max_clips`` below the default ``min_clips``, ``min_clips``
    auto-caps to ``max_clips`` to avoid surprise. An explicit
    ``min_clips > max_clips`` is treated as an inconsistency.
    """

    min_duration: float = Field(default=15.0, gt=0.0)
    max_duration: float = Field(default=180.0, gt=0.0)
    min_clips: int = Field(default=3, ge=0)
    max_clips: int = Field(default=8, ge=1)
    signal_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    window_stride: float = Field(default=8.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_window(self) -> HighlightDiscoveryConfig:
        if self.max_duration <= self.min_duration:
            raise ValueError("max_duration must be strictly greater than min_duration")
        if "min_clips" not in self.model_fields_set and self.min_clips > self.max_clips:
            object.__setattr__(self, "min_clips", self.max_clips)
        if self.min_clips > self.max_clips:
            raise ValueError("min_clips must be <= max_clips")
        return self


class HighlightDiscoveryResult(ValueObject):
    """The deterministic output of :func:`discover_highlights`."""

    candidates: tuple[CandidateMoment, ...]
    config: HighlightDiscoveryConfig
    source_segment_count: int = Field(ge=0)
    discovered_at_offsets: tuple[float, ...] = ()


# --- Canonical hashing helper ------------------------------------------------


_WHITESPACE_RE = re.compile(r"\s+")


def canonical_dedup_key(
    *,
    start: float,
    end: float,
    excerpt: str,
    sensitivity: SensitivityLevel,
) -> str:
    """Stable ``dedup_key`` over (start_ms, end_ms, excerpt, sensitivity).

    Floats are quantised to whole milliseconds so deterministic re-runs with
    sub-millisecond float drift collapse to one key.
    """

    payload = {
        "start_ms": round(start * 1000.0),
        "end_ms": round(end * 1000.0),
        "excerpt": _WHITESPACE_RE.sub(" ", excerpt).strip().lower(),
        "sensitivity": sensitivity,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]
