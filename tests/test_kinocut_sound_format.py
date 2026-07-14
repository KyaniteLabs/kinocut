"""RED-first tests for the ``kinocut_sound`` audio format contract.

A format binds a channel layout, sample rate, sample format, time base, and the
explicit conversion/dither policy applied to every input, bus, stem, and master.
Implicit upmix is rejected; downmix is allowed only when an ITU-R BS.775-style
named preset is supplied. The contract is fail-closed and structural.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.format import (
    AudioFormat,
    ChannelLayout,
    ConversionPolicy,
    DitherPolicy,
    SampleFormat,
    TimeBase,
    CHANNEL_COUNT,
)


def test_channel_layouts_are_closed_and_map_to_counts():
    assert {layout.value for layout in ChannelLayout} == {
        "mono",
        "stereo",
        "surround_5_1",
        "surround_7_1",
    }
    assert CHANNEL_COUNT[ChannelLayout.MONO] == 1
    assert CHANNEL_COUNT[ChannelLayout.STEREO] == 2
    assert CHANNEL_COUNT[ChannelLayout.SURROUND_5_1] == 6
    assert CHANNEL_COUNT[ChannelLayout.SURROUND_7_1] == 8


def test_sample_formats_are_closed():
    assert {fmt.value for fmt in SampleFormat} == {
        "pcm_s16le",
        "pcm_s24le",
        "pcm_s32le",
        "float_32",
    }


def test_time_bases_are_closed():
    assert {tb.value for tb in TimeBase} == {"continuous", "ntsc_drop", "ntsc_nondrop", "pal"}


def test_dither_policies_are_closed():
    assert {d.value for d in DitherPolicy} == {"none", "triangular", "rectangular"}


def test_audio_format_accepts_valid_layout_and_rate():
    fmt = AudioFormat(
        channel_layout=ChannelLayout.STEREO,
        sample_rate_hz=48000,
        sample_format=SampleFormat.PCM_S24LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.TRIANGULAR,
    )
    assert fmt.channel_count == 2
    assert fmt.sample_rate_hz == 48000


def test_audio_format_rejects_non_positive_or_non_integer_sample_rate():
    for bad in (0, -44100, 44100.5, 48000.0):
        with pytest.raises(ValidationError):
            AudioFormat(
                channel_layout=ChannelLayout.STEREO,
                sample_rate_hz=bad,
                sample_format=SampleFormat.PCM_S24LE,
                time_base=TimeBase.CONTINUOUS,
                conversion=ConversionPolicy(),
                dither=DitherPolicy.NONE,
            )


def test_conversion_policy_rejects_implicit_upmix_and_requires_named_downmix():
    with pytest.raises(ValidationError):
        ConversionPolicy(allow_implicit_upmix=True)
    no_downmix = ConversionPolicy(allowed_downmix_presets=(), allow_implicit_upmix=False)
    assert no_downmix.allow_implicit_upmix is False
    named = ConversionPolicy(
        allowed_downmix_presets=("itu_r_bs775_5_1_to_stereo",),
        allow_implicit_upmix=False,
    )
    assert named.allowed_downmix_presets == ("itu_r_bs775_5_1_to_stereo",)


def test_conversion_policy_rejects_unbounded_preset_codes():
    for bad in ("with space", "../secret", "https://x"):
        with pytest.raises(ValidationError):
            ConversionPolicy(allowed_downmix_presets=(bad,), allow_implicit_upmix=False)


def test_audio_format_is_frozen():
    fmt = AudioFormat(
        channel_layout=ChannelLayout.MONO,
        sample_rate_hz=44100,
        sample_format=SampleFormat.PCM_S16LE,
        time_base=TimeBase.CONTINUOUS,
        conversion=ConversionPolicy(),
        dither=DitherPolicy.NONE,
    )
    with pytest.raises(ValidationError):
        fmt.sample_rate_hz = 48000  # type: ignore[misc]
