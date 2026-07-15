"""Editorial planning contracts: beat map (design §4.7, #42).

A beat map elaborates an acceptance spec's free-form ``semantic_beats`` into
ordered, requirement-bearing :class:`BeatRequirement` entries that the coverage
report (#43) can resolve against approved clips. It is canonical, append-only
state bound to one acceptance spec.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import field_validator

from kinocut.contracts._common import RecordBase, Sha256, ValueObject

_CODE_RE = re.compile(r"^[a-z][a-z0-9_.]{0,63}$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.\-_'()]{0,127}$")


def _codes(values: tuple[str, ...]) -> tuple[str, ...]:
    for value in values:
        if not _CODE_RE.match(value):
            raise ValueError("value must be a bounded lowercase code")
    return values


class BeatRequirement(ValueObject):
    """One planned beat with optional required subjects."""

    beat_id: str
    label: str
    required_subjects: tuple[str, ...] = ()

    @field_validator("beat_id")
    @classmethod
    def _beat_id_is_code(cls, value: str) -> str:
        if not _CODE_RE.match(value):
            raise ValueError("beat_id must be a bounded lowercase code")
        return value

    @field_validator("label")
    @classmethod
    def _label_is_advisory(cls, value: str) -> str:
        if not _LABEL_RE.match(value):
            raise ValueError("label must be short advisory text")
        return value

    @field_validator("required_subjects")
    @classmethod
    def _subjects_are_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _codes(value)


class BeatMap(RecordBase):
    """An ordered set of beat requirements bound to an acceptance spec (#42)."""

    record_kind: Literal["beat_map"] = "beat_map"

    acceptance_spec_id: Sha256
    beats: tuple[BeatRequirement, ...]

    @field_validator("beats")
    @classmethod
    def _beats_nonempty_with_unique_ids(cls, value: tuple[BeatRequirement, ...]) -> tuple[BeatRequirement, ...]:
        if not value:
            raise ValueError("a beat map requires at least one beat")
        beat_ids = [beat.beat_id for beat in value]
        if len(set(beat_ids)) != len(beat_ids):
            raise ValueError("beat_ids must be unique")
        return value


__all__ = ["BeatMap", "BeatRequirement", "ContinuityExpectation", "ContinuityPlan"]


class ContinuityExpectation(ValueObject):
    """One shot's declarative continuity expectation (#45)."""

    shot_id: str
    expected_subjects: tuple[str, ...] = ()
    forbidden_changes: tuple[str, ...] = ()

    @field_validator("shot_id")
    @classmethod
    def _shot_id_is_code(cls, value: str) -> str:
        if not _CODE_RE.match(value):
            raise ValueError("shot_id must be a bounded lowercase code")
        return value

    @field_validator("expected_subjects", "forbidden_changes")
    @classmethod
    def _fields_are_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _codes(value)


class ContinuityPlan(RecordBase):
    """A declarative inter-shot continuity contract bound to a spec (#45)."""

    record_kind: Literal["continuity_plan"] = "continuity_plan"

    acceptance_spec_id: Sha256
    expectations: tuple[ContinuityExpectation, ...]

    @field_validator("expectations")
    @classmethod
    def _expectations_nonempty_with_unique_ids(
        cls, value: tuple[ContinuityExpectation, ...]
    ) -> tuple[ContinuityExpectation, ...]:
        if not value:
            raise ValueError("a continuity plan requires at least one expectation")
        shot_ids = [item.shot_id for item in value]
        if len(set(shot_ids)) != len(shot_ids):
            raise ValueError("shot_ids must be unique")
        return value
