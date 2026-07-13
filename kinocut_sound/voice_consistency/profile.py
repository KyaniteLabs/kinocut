"""Versioned voice profile model.

A :class:`VoiceProfile` is a stable, versioned identity that binds a roster
slot to a reference render hash, provenance, default prosody, render
fingerprint, and a consent grant ref. It carries no raw text, host path, or
credential.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound.limits import MIN_VERSION
from kinocut_sound.lines import Prosody
from kinocut_sound.render_fingerprint import RenderFingerprint
from kinocut_sound.sound_plan import PlanProvenance

from kinocut_sound.voice_consistency._errors import (
    CONSISTENCY_PROFILE_INVALID,
    bounded_consistency_error,
)


class VoiceProfile(FrozenModel):
    """One versioned voice profile.

    ``profile_id`` is a bounded public identifier. ``version`` is a positive
    integer. ``slot_id`` names a roster slot compiled elsewhere. Every
    textual or binary payload is represented by a bounded SHA-256 hash so no
    raw protected content leaks through the profile surface.
    """

    profile_id: str = Field(min_length=1)
    version: int = Field(ge=MIN_VERSION)
    slot_id: str = Field(min_length=1)
    reference_hash: Sha256
    provenance: PlanProvenance
    defaults: Prosody
    fingerprint: RenderFingerprint
    consent_grant_ref: str = Field(min_length=1)

    @field_validator("profile_id", "slot_id", "consent_grant_ref")
    @classmethod
    def _bounded_codes(cls, value: str) -> str:
        try:
            return BoundedCode(value)
        except (TypeError, ValueError) as exc:
            raise bounded_consistency_error(
                "profile field must be a bounded code",
                CONSISTENCY_PROFILE_INVALID,
            ) from exc

    @field_validator("version", mode="before")
    @classmethod
    def _version_is_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise bounded_consistency_error(
                "profile version must be a positive integer",
                CONSISTENCY_PROFILE_INVALID,
            )
        return value
