"""Delivery policy: loudness preset, true-peak, stems, recombination, metadata.

The delivery binds the named loudness preset (ruling #5/#9: stream_-14 default,
podcast_-16, broadcast_ebu_r128_-23, broadcast_atsc_a85_-24), the true-peak
ceiling, the typed stem layout, the deterministic stem-recombination policy,
and the bounded distribution-metadata codes. The named presets are standards-
specific and never aliases for one another.

Design references (sonic-world design):
* Reconciled conflicts #5/#9 — named presets and their numeric targets.
* Numeric mix policy — true-peak ceilings stream/podcast -1.0, EBU/ATSC -2.0;
  stem recombination versus master peak absolute error <=1 LSB at 24-bit.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel

# Numeric defaults (design §"RenderFingerprint & numeric mix policy").
LOUDNESS_TOLERANCE_LU = 1.0
STREAM_PODCAST_TRUE_PEAK_DBTP = -1.0
BROADCAST_TRUE_PEAK_DBTP = -2.0
STEM_RECOMBINATION_TOLERANCE_LSB_24BIT = 1


class DeliveryPreset(StrEnum):
    """The closed set of named delivery loudness presets (ruling #5/#9)."""

    STREAM_MINUS_14 = "stream_-14"
    PODCAST_MINUS_16 = "podcast_-16"
    BROADCAST_EBU_R128_MINUS_23 = "broadcast_ebu_r128_-23"
    BROADCAST_ATSC_A85_MINUS_24 = "broadcast_atsc_a85_-24"


DEFAULT_PRESET: DeliveryPreset = DeliveryPreset.STREAM_MINUS_14

# Per-preset integrated LUFS targets (ruling #5/#9).
_PRESET_LUFS: dict[DeliveryPreset, float] = {
    DeliveryPreset.STREAM_MINUS_14: -14.0,
    DeliveryPreset.PODCAST_MINUS_16: -16.0,
    DeliveryPreset.BROADCAST_EBU_R128_MINUS_23: -23.0,
    DeliveryPreset.BROADCAST_ATSC_A85_MINUS_24: -24.0,
}

# Per-preset true-peak ceilings: stream/podcast use -1.0, broadcast uses -2.0.
_PRESET_TRUE_PEAK_DBTP: dict[DeliveryPreset, float] = {
    DeliveryPreset.STREAM_MINUS_14: STREAM_PODCAST_TRUE_PEAK_DBTP,
    DeliveryPreset.PODCAST_MINUS_16: STREAM_PODCAST_TRUE_PEAK_DBTP,
    DeliveryPreset.BROADCAST_EBU_R128_MINUS_23: BROADCAST_TRUE_PEAK_DBTP,
    DeliveryPreset.BROADCAST_ATSC_A85_MINUS_24: BROADCAST_TRUE_PEAK_DBTP,
}


class LoudnessTarget(FrozenModel):
    """One loudness target with integrated LUFS, tolerance, and true-peak."""

    integrated_lufs: float = Field(lt=0.0)
    tolerance_lu: float = Field(default=LOUDNESS_TOLERANCE_LU, gt=0.0, le=2.0)
    true_peak_dbtp: float = Field(lt=0.0)

    @field_validator("integrated_lufs", "tolerance_lu", "true_peak_dbtp")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @classmethod
    def for_preset(cls, preset: DeliveryPreset) -> LoudnessTarget:
        return cls(
            integrated_lufs=_PRESET_LUFS[preset],
            tolerance_lu=LOUDNESS_TOLERANCE_LU,
            true_peak_dbtp=_PRESET_TRUE_PEAK_DBTP[preset],
        )


class StemLayout(FrozenModel):
    """A typed stem layout: unique, bounded stem ids."""

    stem_ids: tuple[str, ...] = ()

    @field_validator("stem_ids")
    @classmethod
    def _stem_ids_are_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for stem_id in value:
            BoundedCode(stem_id)
        if len(set(value)) != len(value):
            raise ValueError("stem ids must be unique")
        return value


class StemRecombinationPolicy(FrozenModel):
    """How stems recombine: tolerance in LSB at 24-bit and a comparison ref.

    ``comparison_reference`` is closed: ``pre_master`` (compare to the
    pre-master mix) or ``post_master`` (compare to the released master). When
    master-only limiting is enabled, the comparison must be ``pre_master`` so
    the master-only chain can be bypassed for the equality proof.
    """

    tolerance_lsb_at_24bit: int = Field(default=STEM_RECOMBINATION_TOLERANCE_LSB_24BIT, ge=0, le=STEM_RECOMBINATION_TOLERANCE_LSB_24BIT)
    comparison_reference: str = "pre_master"

    @field_validator("comparison_reference")
    @classmethod
    def _reference_is_closed(cls, value: str) -> str:
        if value not in {"pre_master", "post_master"}:
            raise ValueError("comparison_reference must be 'pre_master' or 'post_master'")
        return value

    @field_validator("tolerance_lsb_at_24bit", mode="before")
    @classmethod
    def _tolerance_is_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("tolerance_lsb_at_24bit must be an integer")
        return value


class DeliveryPolicy(FrozenModel):
    """The complete delivery policy for a SoundPlan."""

    preset: DeliveryPreset = DEFAULT_PRESET
    loudness: LoudnessTarget = Field(default_factory=lambda: LoudnessTarget.for_preset(DEFAULT_PRESET))
    true_peak_ceiling_dbtp: float = Field(default=STREAM_PODCAST_TRUE_PEAK_DBTP, le=0.0)
    stems: StemLayout = Field(default_factory=StemLayout)
    recombination: StemRecombinationPolicy = Field(default_factory=StemRecombinationPolicy)
    metadata_codes: tuple[str, ...] = ()
    master_only_limiting_enabled: bool = False

    @field_validator("metadata_codes")
    @classmethod
    def _metadata_codes_are_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("metadata codes must be unique")
        return value

    @field_validator("true_peak_ceiling_dbtp")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("numeric field must not be a boolean")
        return value

    @model_validator(mode="after")
    def _master_only_limiting_requires_pre_master_reference(self) -> DeliveryPolicy:
        if self.master_only_limiting_enabled and self.recombination.comparison_reference != "pre_master":
            raise ValueError(
                "master-only limiting requires recombination.comparison_reference == 'pre_master'"
            )
        return self
