"""``DefectFinding`` with its stable taxonomy and status (design §4.5).

The taxonomy is a closed, versioned set. A finding whose status is anything
other than ``suspected`` must carry a human decision reference.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from kinocut.contracts._common import (
    AssetId,
    NormalizedRegion,
    RecordBase,
    Sha256,
    ValueObject,
)

# Bump only additively; readers key migrations off this version (design §4.5).
TAXONOMY_VERSION = 1


class DefectCode(StrEnum):
    """The stable initial defect taxonomy (design §4.5)."""

    TEXT_DRIFT = "text_drift"
    IDENTITY_DRIFT = "identity_drift"
    OBJECT_MUTATION = "object_mutation"
    WARPING = "warping"
    FLICKER = "flicker"
    UNWANTED_CAMERA_MOTION = "unwanted_camera_motion"
    CONTINUITY_FAILURE = "continuity_failure"
    LATE_FRAME_DEGRADATION = "late_frame_degradation"
    FROZEN_FRAMES = "frozen_frames"
    BLACK_FRAMES = "black_frames"
    CORRUPT_FRAMES = "corrupt_frames"
    BROKEN_LOOP = "broken_loop"
    SUBTITLE_OVERFLOW = "subtitle_overflow"
    SUBTITLE_TIMING = "subtitle_timing"
    AUDIO_DURATION = "audio_duration"
    AUDIO_STYLE_SEAM = "audio_style_seam"
    VOICE_IDENTITY_SEAM = "voice_identity_seam"


class DefectStatus(StrEnum):
    """Lifecycle of a defect finding; only ``suspected`` needs no human call."""

    SUSPECTED = "suspected"
    CONFIRMED = "confirmed"
    ACCEPTED_LIMITATION = "accepted_limitation"
    RESOLVED = "resolved"
    FALSE_POSITIVE = "false_positive"


class Severity(StrEnum):
    """Bounded severity ladder for a defect finding."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Measurement(ValueObject):
    """A single named, unit-carrying measurement backing a finding."""

    name: str
    value: float
    unit: str


class DefectFinding(RecordBase):
    """A defect observed on an asset or artifact over an exact time range."""

    record_kind: Literal["defect_finding"] = "defect_finding"

    defect_code: DefectCode
    taxonomy_version: Literal[1] = TAXONOMY_VERSION
    target_id: AssetId
    time_range: tuple[float, float]
    spatial_region: NormalizedRegion | None = None
    severity: Severity
    confidence: float = Field(ge=0.0, le=1.0)
    detector: str
    measurements: tuple[Measurement, ...] = ()
    evidence_artifact_ids: tuple[Sha256, ...] = ()
    status: DefectStatus = DefectStatus.SUSPECTED
    human_decision_id: Sha256 | None = None

    @field_validator("taxonomy_version", mode="before")
    @classmethod
    def _taxonomy_version_is_strict_int(cls, value: Any) -> Any:
        """Reject coerced versions (``True``, ``1.0``, ``"1"``) before the literal."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("taxonomy_version must be the integer 1")
        return value

    @model_validator(mode="after")
    def _validate_status_and_range(self) -> DefectFinding:
        """Positive, nonnegative time range; non-suspected status needs a human call."""

        start, end = self.time_range
        if start < 0.0 or end <= start:
            raise ValueError("time_range must be a positive, nonnegative range")
        if self.status is not DefectStatus.SUSPECTED and self.human_decision_id is None:
            raise ValueError(f"status {self.status.value!r} requires a human_decision_id")
        return self
