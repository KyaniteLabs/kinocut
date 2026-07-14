"""Edit-receipt v1 contract for the governed audio-bed primitive.

This receipt follows the shared edit-receipt-v1 substrate described in the
field-wishlist design: ``schema_version: 1``, ``receipt_kind: "edit"``, ordered
inputs with privacy-safe display names and content hashes, normalized
parameters, output identity, toolchain fingerprint, warning codes, and a
deterministic receipt hash. Absolute source paths are structurally
unrepresentable — every identity-like field is a content hash or a bounded
safe display name (basename only, no directory components).

The whole receipt is a frozen :class:`~pydantic.BaseModel` so it can be
canonicalised for the deterministic receipt hash without mutation risk.
"""

from __future__ import annotations


from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kinocut.contracts._common import Sha256
from kinocut.limits import (
    MAX_AUDIO_BED_DUCK_ATTACK_MS,
    MAX_AUDIO_BED_DUCK_RATIO,
    MAX_AUDIO_BED_DUCK_RELEASE_MS,
    MAX_AUDIO_BED_DUCK_THRESHOLD,
    MAX_AUDIO_BED_FADE_SECONDS,
    MAX_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
    MAX_AUDIO_BED_MUSIC_VOLUME,
    MAX_AUDIO_BED_TARGET_LUFS,
    MIN_AUDIO_BED_DUCK_ATTACK_MS,
    MIN_AUDIO_BED_DUCK_RATIO,
    MIN_AUDIO_BED_DUCK_RELEASE_MS,
    MIN_AUDIO_BED_DUCK_THRESHOLD,
    MIN_AUDIO_BED_FADE_SECONDS,
    MIN_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
    MIN_AUDIO_BED_MUSIC_VOLUME,
    MIN_AUDIO_BED_TARGET_LUFS,
)
from kinocut.validation import (
    AUDIO_BED_SAFE_CODE_RE,
    AUDIO_BED_SAFE_DISPLAY_RE,
    AUDIO_BED_SAFE_TOOLCHAIN_KEY_RE,
)


class AudioBedInput(BaseModel):
    """One ordered input to the audio-bed operation, identified by content hash."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    role: Literal["voice_source", "music_bed"]
    content_sha256: Sha256
    probed_duration_seconds: float = Field(ge=0.0)
    display_name: str = Field(min_length=1, max_length=128)
    has_audio_stream: bool

    @field_validator("display_name")
    @classmethod
    def _safe_display(cls, value: str) -> str:
        if AUDIO_BED_SAFE_DISPLAY_RE.fullmatch(value) is None:
            raise ValueError("display_name must be a bounded basename (no paths or prose)")
        return value


class AudioBedParameters(BaseModel):
    """Normalized, bounded parameters bound to the audio-bed render."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    loop: bool
    music_volume: float = Field(ge=MIN_AUDIO_BED_MUSIC_VOLUME, le=MAX_AUDIO_BED_MUSIC_VOLUME)
    loop_crossfade_seconds: float = Field(
        ge=MIN_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
        le=MAX_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
    )
    fade_in_seconds: float = Field(ge=MIN_AUDIO_BED_FADE_SECONDS, le=MAX_AUDIO_BED_FADE_SECONDS)
    fade_out_seconds: float = Field(ge=MIN_AUDIO_BED_FADE_SECONDS, le=MAX_AUDIO_BED_FADE_SECONDS)
    target_lufs: float = Field(ge=MIN_AUDIO_BED_TARGET_LUFS, le=MAX_AUDIO_BED_TARGET_LUFS)
    duck_threshold: float = Field(ge=MIN_AUDIO_BED_DUCK_THRESHOLD, le=MAX_AUDIO_BED_DUCK_THRESHOLD)
    duck_ratio: float = Field(ge=MIN_AUDIO_BED_DUCK_RATIO, le=MAX_AUDIO_BED_DUCK_RATIO)
    duck_attack_ms: float = Field(ge=MIN_AUDIO_BED_DUCK_ATTACK_MS, le=MAX_AUDIO_BED_DUCK_ATTACK_MS)
    duck_release_ms: float = Field(ge=MIN_AUDIO_BED_DUCK_RELEASE_MS, le=MAX_AUDIO_BED_DUCK_RELEASE_MS)
    duration_policy: Literal["keep_video"] = "keep_video"


class AudioBedReceipt(BaseModel):
    """Edit-receipt v1 emitted by the governed audio-bed primitive."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    receipt_kind: Literal["edit"] = "edit"
    operation: Literal["audio_bed"] = "audio_bed"
    inputs: tuple[AudioBedInput, ...] = Field(min_length=2, max_length=2)
    parameters: AudioBedParameters
    output_content_sha256: Sha256
    output_duration_seconds: float = Field(ge=0.0)
    output_display_name: str = Field(min_length=1, max_length=128)
    ducking_engaged: bool
    loudness_filter: Literal["loudnorm"] = "loudnorm"
    warnings: tuple[str, ...] = ()
    human_review_required: bool = True
    toolchain: tuple[tuple[str, str | None], ...] = ()
    receipt_sha256: Sha256 | None = None

    @field_validator("output_display_name")
    @classmethod
    def _safe_output_display(cls, value: str) -> str:
        if AUDIO_BED_SAFE_DISPLAY_RE.fullmatch(value) is None:
            raise ValueError("output_display_name must be a bounded basename (no paths or prose)")
        return value

    @field_validator("warnings")
    @classmethod
    def _safe_warnings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for v in values:
            if AUDIO_BED_SAFE_CODE_RE.fullmatch(v) is None:
                raise ValueError("warning codes must be bounded identifiers")
        return values

    @field_validator("toolchain")
    @classmethod
    def _safe_toolchain(cls, values: tuple[tuple[str, str | None], ...]) -> tuple[tuple[str, str | None], ...]:
        for key, _val in values:
            if AUDIO_BED_SAFE_TOOLCHAIN_KEY_RE.fullmatch(key) is None:
                raise ValueError("toolchain keys must be bounded identifiers")
        return values
