"""Line and profile reference contracts — no raw text, hashes only.

A line binds a character id to a profile ref plus prosody, emotion, spatial
preset, pronunciation overrides, and loudness inheritance. Raw text is never
carried — only its bounded SHA-256 hash and length — so a serialized line or
receipt cannot leak a script or transcript. Profile refs are bounded codes
that carry version, so a render is reproducible and auditable.

Design references (sonic-world design):
* Core contracts §"SoundPlan" (lines) and §"VoiceProfile".
* Privacy & security — prompts and transcripts are hashes only.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.defaults import (
    DEFAULT_PROSODY_EMPHASIS,
    DEFAULT_PROSODY_PITCH_SEMITONES,
    DEFAULT_PROSODY_RATE,
    DEFAULT_PROSODY_VOLUME_DB,
)
from kinocut_sound.limits import (
    MAX_NORMALIZED_LEVEL,
    MAX_PROSODY_PITCH_SEMITONES,
    MAX_PROSODY_RATE,
    MAX_PROSODY_VOLUME_DB,
    MIN_NORMALIZED_LEVEL,
    MIN_PROSODY_PITCH_SEMITONES,
    MIN_PROSODY_RATE,
    MIN_PROSODY_VOLUME_DB,
    MIN_TEXT_LENGTH_CHARS,
    MIN_VERSION,
)


class ProfileRef(FrozenModel):
    """A typed, versioned reference to a VoiceProfile owned elsewhere."""

    profile_id: str = Field(min_length=1)
    version: int = Field(ge=MIN_VERSION)

    @field_validator("profile_id")
    @classmethod
    def _profile_id_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("version must be a positive integer")
        return value


class Prosody(FrozenModel):
    """Per-line prosody overrides: rate, pitch, volume, emphasis.

    ``rate`` is a multiplier around 1.0 (0.5x-2.0x supported range; clamped
    tighter here to a musical band). ``pitch`` is a semitone offset. Volume is
    a dB offset. Emphasis is a 0..1 intensity.
    """

    rate: float = Field(default=DEFAULT_PROSODY_RATE, gt=MIN_PROSODY_RATE, le=MAX_PROSODY_RATE)
    pitch: float = Field(default=DEFAULT_PROSODY_PITCH_SEMITONES, ge=MIN_PROSODY_PITCH_SEMITONES, lt=MAX_PROSODY_PITCH_SEMITONES)
    volume_db: float = Field(default=DEFAULT_PROSODY_VOLUME_DB, ge=MIN_PROSODY_VOLUME_DB, le=MAX_PROSODY_VOLUME_DB)
    emphasis: float = Field(default=DEFAULT_PROSODY_EMPHASIS, ge=MIN_NORMALIZED_LEVEL, le=MAX_NORMALIZED_LEVEL)


class Emotion(FrozenModel):
    """A bounded emotion label paired with a 0..1 intensity."""

    label: str = Field(min_length=1)
    intensity: float = Field(ge=MIN_NORMALIZED_LEVEL, le=MAX_NORMALIZED_LEVEL)

    @field_validator("label")
    @classmethod
    def _label_is_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("intensity")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("intensity must not be a boolean")
        return value


class PronunciationOverride(FrozenModel):
    """One project-term pronunciation override, identified by hash."""

    term_hash: Sha256
    ipa: str = Field(min_length=1)

    @field_validator("ipa")
    @classmethod
    def _ipa_is_bounded(cls, value: str) -> str:
        # IPA is bounded: no whitespace, no host paths, no control chars.
        if any(ord(ch) < 0x20 for ch in value):
            raise ValueError("ipa must not contain control characters")
        if any(ch.isspace() for ch in value):
            raise ValueError("ipa must not contain whitespace")
        if "/" in value or "\\" in value:
            raise ValueError("ipa must not contain path separators")
        if len(value) > 64:
            raise ValueError("ipa must be at most 64 chars")
        return value


class Line(FrozenModel):
    """One character line: text hash + profile ref + prosody + spatial."""

    line_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    profile: ProfileRef
    text_hash: Sha256
    text_length_chars: int = Field(ge=MIN_TEXT_LENGTH_CHARS)
    prosody: Prosody
    emotion: Emotion
    spatial_preset: str = Field(min_length=1)
    pronunciation_overrides: tuple[PronunciationOverride, ...] = ()
    inherit_loudness: bool

    @field_validator("line_id", "character_id", "spatial_preset")
    @classmethod
    def _ids_are_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("text_length_chars")
    @classmethod
    def _length_is_strict_int(cls, value: int) -> int:
        if isinstance(value, bool):
            raise ValueError("text_length_chars must be an integer")
        return value
