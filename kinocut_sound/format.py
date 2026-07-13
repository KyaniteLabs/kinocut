"""Audio format contract: layout, rate, sample shape, conversion policy.

A format binds the channel layout, sample rate, sample format, time base, and
the explicit conversion/dither policy applied to every input, bus, stem, and
master of a SoundPlan. Implicit upmix is structurally rejected; downmix is
allowed only when a named standards-based preset is supplied (e.g. ITU-R
BS.775 5.1-to-stereo). The closed enums match the design's reconciled ruling #9
and the wishlist §2.7 loudness layout expectations.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel


class ChannelLayout(StrEnum):
    """The closed set of channel layouts a SoundPlan may target."""

    MONO = "mono"
    STEREO = "stereo"
    SURROUND_5_1 = "surround_5_1"
    SURROUND_7_1 = "surround_7_1"


class SampleFormat(StrEnum):
    """The closed set of PCM sample formats a plan may carry."""

    PCM_S16LE = "pcm_s16le"
    PCM_S24LE = "pcm_s24le"
    PCM_S32LE = "pcm_s32le"
    FLOAT_32 = "float_32"


class TimeBase(StrEnum):
    """The closed set of timeline clock bases a plan may declare."""

    CONTINUOUS = "continuous"
    NTSC_DROP = "ntsc_drop"
    NTSC_NONDROP = "ntsc_nondrop"
    PAL = "pal"


class DitherPolicy(StrEnum):
    """The closed set of dither policies permitted on sample-format conversion."""

    NONE = "none"
    TRIANGULAR = "triangular"
    RECTANGULAR = "rectangular"


# Canonical channel counts per layout — used by routing/mixing invariants.
CHANNEL_COUNT: dict[ChannelLayout, int] = {
    ChannelLayout.MONO: 1,
    ChannelLayout.STEREO: 2,
    ChannelLayout.SURROUND_5_1: 6,
    ChannelLayout.SURROUND_7_1: 8,
}


class ConversionPolicy(FrozenModel):
    """How a format may be converted — fail-closed against silent upmix.

    ``allow_implicit_upmix`` is structural False: a channel-count increase is
    rejected unless the plan explicitly names a standards-based downmix preset
    in ``allowed_downmix_presets``. A preset is a bounded code so a host path,
    URL, or prose cannot ride in on it.
    """

    allow_implicit_upmix: bool = False
    allowed_downmix_presets: tuple[str, ...] = ()

    @field_validator("allowed_downmix_presets")
    @classmethod
    def _presets_are_bounded_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for preset in value:
            BoundedCode(preset)
        if len(set(value)) != len(value):
            raise ValueError("allowed_downmix_presets must be unique")
        return value

    @field_validator("allow_implicit_upmix")
    @classmethod
    def _upmix_always_disabled(cls, value: bool) -> bool:
        if value is True:
            raise ValueError("implicit upmix is prohibited; name an explicit downmix preset instead")
        return value


class AudioFormat(FrozenModel):
    """One typed audio format binding for an input, bus, stem, or master."""

    channel_layout: ChannelLayout
    sample_rate_hz: int = Field(gt=0)
    sample_format: SampleFormat
    time_base: TimeBase
    conversion: ConversionPolicy
    dither: DitherPolicy

    @field_validator("sample_rate_hz", mode="before")
    @classmethod
    def _rate_is_strict_positive_int(cls, value: object) -> object:
        """Reject coerced or non-integer rates (e.g. ``48000.0``)."""

        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("sample_rate_hz must be a positive integer")
        return value

    @property
    def channel_count(self) -> int:
        """The canonical channel count for this layout."""

        return CHANNEL_COUNT[self.channel_layout]
