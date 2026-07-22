"""Strict product-domain models for the long-form stream-to-shorts workflow.

The models in this module are the *public contract* for moment discovery and
downstream ShortsPlan composition. Every model is:

* **Strict** — ``extra="forbid"``, ``frozen=True``, ``allow_inf_nan=False`` so a
  caller cannot smuggle unknown fields, mutate state, or sneak a NaN into a
  canonical JSON payload.
* **JSON-stable** — every field round-trips through ``model_dump(mode="json")``
  with sorted keys + compact separators; ``dedup_key`` is a stable sha256 hex
  digest that other slices can reproduce byte-for-byte.
* **Decoupled from engines** — these are VALUE OBJECTS, not records. The
  downstream render-op emission (which lives in
  ``kinocut.product.shorts``/``kinocut.workflow.executor``) consumes these
  models but never the other way around. No engine import is performed here.

Human review remains mandatory before any render: every :class:`CandidateMoment`
carries a ``review_warning`` (or ``None`` when none applies) and an
``unsuitable`` flag so reviewers can act on the proposal rather than accept it
blind.
"""

from __future__ import annotations
from collections.abc import Mapping

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


# --- Bounded string patterns -------------------------------------------------

# ``segment_id`` is a caller-supplied identifier for a transcript segment. It is
# intentionally permissive (ascii identifier characters plus ``-``/``_``/``.``)
# because the producer (long-form transcription slice) owns the naming scheme.
_SEGMENT_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"

# ``dedup_key`` is the canonical 16-hex-char prefix of a sha256 over the
# stable semantic content of a candidate (start, end, sensitivity, normalised
# excerpt). Two logically-equal candidates MUST hash to the same key.
_DEDUP_KEY_PATTERN = r"^[0-9a-f]{16}$"

# ``sensitivity`` is an ordinal progression callers (and the review surface) can
# match on without re-parsing prose. ``unsafe`` is reserved for material that
# must NOT be auto-rendered even if accepted; the orchestrator treats it as a
# hard block.
SensitivityLevel = Literal["none", "mild", "strong", "unsafe"]


# --- Strict base -------------------------------------------------------------


class _StrictModel(BaseModel):
    """Frozen, unknown-field-rejecting base for every model in this module."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


# --- Inputs ------------------------------------------------------------------


class TranscriptSegment(_StrictModel):
    """One timed span of transcript text.

    The discovery layer treats segments as the smallest unit of analysis; they
    may come from a long-form transcription slice that emits word-grouped
    phrases or coarse sentence-level chunks. ``speaker`` and ``confidence`` are
    optional because some upstream emitters only carry them when they have a
    reliable value. ``is_silence`` lets the discovery layer honour the
    "no leading silence" rule without re-running silence detection.
    """

    segment_id: str = Field(pattern=_SEGMENT_ID_PATTERN)
    start: float = Field(ge=0.0)
    end: float = Field(gt=0.0)
    text: str = Field(min_length=1)
    speaker: str | None = Field(default=None, min_length=1)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    is_silence: bool = False

    @model_validator(mode="after")
    def _validate_time_range(self) -> TranscriptSegment:
        """A segment's end must be strictly greater than its start.

        Zero-width segments cannot anchor a moment boundary and would otherwise
        leak into the candidate window; reject them at the input boundary so
        the discovery layer never has to defend against them.
        """

        if self.end <= self.start:
            raise ValueError("transcript segment end must be strictly greater than start")
        return self


class TranscriptWord(_StrictModel):
    """One timed word/token emitted by the long-form transcription slice.

    Preserved through the orchestrator so caption generation can use real
    Whisper word timings instead of evenly synthesizing them when no real
    timings are available. ``segment_id`` ties the word back to its parent
    :class:`TranscriptSegment` for the caption grouper, which needs the
    segment boundary to clip each word against the candidate window.
    ``probability`` is the per-token log-probability translated to a
    probability in ``[0.0, 1.0]``; ``None`` when the upstream emitter did
    not supply one. Times are source-time seconds and remain absolute —
    caption generation offsets them to the candidate window.
    """

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


class SourceSignal(_StrictModel):
    """One optional evidence signal attached to a candidate.

    Signals are caller-supplied (long-form transcription slice, scene-detect
    slice, audio-engine slice) and the discovery layer uses them only as a
    tie-breaker for the *score* — the *bounds* always come from the transcript.
    ``kind`` is a discriminated literal so a future schema addition is
    fail-closed: any new kind has to be opted in here.
    """

    kind: Literal["scene_change", "audio_energy"]
    timestamp: float = Field(ge=0.0)
    score: float = Field(ge=0.0, le=1.0)
    label: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _validate_score_window(self) -> SourceSignal:
        if not self.score >= 0.0:  # tautology kept explicit for readability
            raise ValueError("source signal score must be >= 0.0")
        return self


# --- Output ------------------------------------------------------------------


class CandidateMoment(_StrictModel):
    """One proposed clip derived from the transcript.

    A candidate is a *suggestion*, not an executable plan. ``start``/``end``
    are the discovery layer's best estimate of where to cut, given the
    complete-thought / no-leading-silence / bounds / duration / payoff rules.
    ``transcript_excerpt`` is the verbatim slice the rule engine chose; the
    surrounding ``context_before`` / ``context_after`` strings (each ``None``
    when not applicable) let a reviewer see what was trimmed off.

    ``dedup_key`` is the stable hash that downstream stages use to collapse
    near-duplicate proposals. ``unsuitable`` is a hard flag for material that
    must never be auto-rendered (e.g. unfinished thoughts, dead air,
    self-harm content). ``sensitivity`` is a soft ordinal: ``none`` is safe to
    publish as-is; ``mild`` may need a content warning; ``strong`` should be
    reviewed before render; ``unsafe`` blocks rendering entirely.
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
        """Enforce the cheap structural invariants of a candidate.

        Numeric bounds, duration, and the "end strictly greater than start"
        rule live here so callers cannot construct an invalid candidate even
        by hand. The semantic rules (complete-thought boundary, no leading
        silence, payoff) are enforced in :func:`discover_highlights` — they
        require transcript context and do not belong on the model.
        """

        if self.end <= self.start:
            raise ValueError("candidate end must be strictly greater than start")
        if self.unsuitable and self.sensitivity != "unsafe":
            # An unsuitable candidate must also declare the unsafe sensitivity
            # so the review surface can match on a single field.
            raise ValueError("unsuitable candidates must declare sensitivity='unsafe'")
        return self


class HighlightDiscoveryConfig(_StrictModel):
    """Tunable knobs for :func:`discover_highlights`.

    Defaults target YouTube Shorts (180 s cap) and Instagram Reels (90 s cap);
    the discovery layer clamps every emitted candidate to the union
    ``[min_duration, max_duration]``. ``min_clips`` is a *target*, not a
    guarantee: degenerate inputs return fewer candidates honestly rather than
    padding the output with weak proposals. ``max_clips`` is a hard cap.
    """

    min_duration: float = Field(default=15.0, gt=0.0)
    max_duration: float = Field(default=180.0, gt=0.0)
    min_clips: int = Field(default=3, ge=0)
    max_clips: int = Field(default=8, ge=1)
    # Scene/audio-signal influence on score (0.0 disables, 1.0 takes over).
    # Always clamped to [0.0, 1.0].
    signal_weight: float = Field(default=0.25, ge=0.0, le=1.0)
    # Sliding-window stride used to enumerate candidate windows. Smaller
    # strides produce more candidates; the discovery layer always dedups.
    window_stride: float = Field(default=8.0, gt=0.0)

    @model_validator(mode="after")
    def _validate_window(self) -> HighlightDiscoveryConfig:
        if self.max_duration <= self.min_duration:
            raise ValueError("max_duration must be strictly greater than min_duration")
        # ``min_clips`` is a *target*; ``max_clips`` is a hard cap. When the
        # operator lowers ``max_clips`` without explicitly choosing a new
        # ``min_clips``, auto-cap ``min_clips`` so the configuration does not
        # surprise them with a validation error. An operator who explicitly
        # sets ``min_clips`` above ``max_clips`` is signalling an inconsistency
        # they must resolve — that case still raises.
        if "min_clips" not in self.model_fields_set and self.min_clips > self.max_clips:
            object.__setattr__(self, "min_clips", self.max_clips)
        if self.min_clips > self.max_clips:
            raise ValueError("min_clips must be <= max_clips")
        return self


class HighlightDiscoveryResult(_StrictModel):
    """The deterministic output of :func:`discover_highlights`.

    The container is JSON-stable: every field is a plain value or a tuple of
    strict models, so the orchestrator can serialise the whole object with
    ``model_dump(mode="json")`` and feed it directly to the human-review
    surface and the downstream ShortsPlan composer.
    """

    candidates: tuple[CandidateMoment, ...]
    config: HighlightDiscoveryConfig
    source_segment_count: int = Field(ge=0)
    discovered_at_offsets: tuple[float, ...] = ()


# --- Canonical hashing helper ------------------------------------------------


def canonical_dedup_key(
    *,
    start: float,
    end: float,
    excerpt: str,
    sensitivity: SensitivityLevel,
) -> str:
    """Compute the stable ``dedup_key`` for a candidate.

    Two candidates whose (start, end, excerpt, sensitivity) are equal MUST
    hash to the same key so downstream dedup is a set-membership test, not a
    fuzzy comparison. Float ``start``/``end`` are quantised to milliseconds
    so that deterministic re-runs with subtly different float arithmetic
    (e.g. ``30.0`` vs ``30.00000001``) collapse to one key.
    """

    payload = {
        "start_ms": round(start * 1000.0),
        "end_ms": round(end * 1000.0),
        # Normalise whitespace so a transcript rendered with different
        # line-ending / spacing choices collapses to the same key.
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


_WHITESPACE_RE = re.compile(r"\s+")


# --- Internal helpers exposed for tests --------------------------------------


def to_jsonable(value: Any) -> Any:
    """Recursively coerce a strict model (or tuple of them) to JSON primitives.

    The orchestrator wants plain JSON; Pydantic's ``model_dump(mode="json")``
    already handles ``datetime``/``Enum`` but it does not deep-coerce nested
    tuples. This helper is the bridge between strict models and the
    ``shorts_plan`` JSON contract.
    """

    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    return value
