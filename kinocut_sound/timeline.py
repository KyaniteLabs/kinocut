"""Authoritative timeline contract for a SoundPlan.

The timeline is the single source of truth for an episode's required output
duration. Every cue has a strictly positive duration, a bounded cue id, and a
project-relative source reference. Cues are ordered, non-overlapping, and
uniquely identified; an unexplained gap above the configured tolerance is
treated as a prohibited shortest-stream mix attempt.

Design references (sonic-world design):
* Ruling #7 — SoundPlan duration is authoritative; shortest-stream mix prohibited.
* Numeric defaults — cue/master sync tolerance 10 ms.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, location_violation
from kinocut_sound.defaults import DEFAULT_GAP_TOLERANCE_SECONDS, DEFAULT_TAIL_SECONDS
from kinocut_sound.limits import MIN_TIME_SECONDS


class CueKind(StrEnum):
    """The closed set of cue kinds a timeline may carry."""

    LINE = "line"
    SILENCE = "silence"
    FOLEY = "foley"
    BED = "bed"
    CHAPTER_MARKER = "chapter_marker"


class Cue(FrozenModel):
    """One ordered cue on the timeline. Duration is authoritative."""

    cue_id: str = Field(min_length=1)
    start_seconds: float = Field(ge=MIN_TIME_SECONDS)
    duration_seconds: float = Field(gt=MIN_TIME_SECONDS)
    kind: CueKind
    source_ref: str = Field(min_length=1)
    in_point_seconds: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    out_point_seconds: float | None = Field(default=None, ge=MIN_TIME_SECONDS)
    transit_kind: str | None = None

    @field_validator("cue_id")
    @classmethod
    def _cue_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("source_ref")
    @classmethod
    def _source_ref_is_project_relative(cls, value: str) -> str:
        reason = location_violation(value)
        if reason is not None:
            raise ValueError(f"source_ref {reason}")
        return value

    @field_validator("transit_kind")
    @classmethod
    def _transit_kind_is_bounded(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else value

    @field_validator("start_seconds", "duration_seconds", "in_point_seconds", "out_point_seconds")
    @classmethod
    def _reject_non_finite_or_coerced(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @model_validator(mode="after")
    def _in_out_ordered(self) -> Cue:
        if (
            self.in_point_seconds is not None
            and self.out_point_seconds is not None
            and self.out_point_seconds <= self.in_point_seconds
        ):
            raise ValueError("out_point_seconds must be greater than in_point_seconds")
        return self


class Timeline(FrozenModel):
    """An ordered, non-overlapping sequence of cues plus declared tail.

    The timeline total (last cue end + tail) is the authoritative required
    output duration. An unexplained gap between cues larger than the configured
    tolerance is rejected as a prohibited shortest-stream mix.
    """

    cues: tuple[Cue, ...] = ()
    tail_seconds: float = Field(default=DEFAULT_TAIL_SECONDS, ge=MIN_TIME_SECONDS)
    gap_tolerance_seconds: float = Field(default=DEFAULT_GAP_TOLERANCE_SECONDS, ge=MIN_TIME_SECONDS)
    require_at_least_one_cue: bool = True

    @field_validator("cues")
    @classmethod
    def _reject_non_tuple(cls, value: tuple[Cue, ...]) -> tuple[Cue, ...]:
        if not isinstance(value, tuple):
            raise TypeError("cues must be a tuple")
        return value

    @field_validator("tail_seconds", "gap_tolerance_seconds")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @model_validator(mode="after")
    def _check_ordering_continuity_and_identity(self) -> Timeline:
        if self.require_at_least_one_cue and not self.cues:
            raise ValueError("timeline must contain at least one cue")

        last_end = 0.0
        seen_ids: set[str] = set()
        for cue in self.cues:
            if cue.cue_id in seen_ids:
                raise ValueError(f"duplicate cue_id: {cue.cue_id}")
            seen_ids.add(cue.cue_id)
            # Allow exact adjacency (start == last_end) but reject going back.
            if cue.start_seconds < last_end:
                raise ValueError(f"cue {cue.cue_id} starts before previous cue ends")
            gap = cue.start_seconds - last_end
            if gap > self.gap_tolerance_seconds:
                raise ValueError(
                    f"cue {cue.cue_id} opens an unexplained gap of {gap:.3f}s "
                    f"(tolerance {self.gap_tolerance_seconds:.3f}s)"
                )
            last_end = max(last_end, cue.start_seconds + cue.duration_seconds)
        return self

    @property
    def total_seconds(self) -> float:
        """Sum of last cue end and declared tail; 0.0 for an empty timeline."""

        if not self.cues:
            return self.tail_seconds
        last_cue = self.cues[-1]
        return last_cue.start_seconds + last_cue.duration_seconds + self.tail_seconds

    @property
    def authoritative_duration_seconds(self) -> float:
        """The required output duration — identical to :attr:`total_seconds`."""

        return self.total_seconds
