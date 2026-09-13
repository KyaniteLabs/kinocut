"""Actual guarded backend framing, channel preservation and audio quality."""

from array import array
import asyncio
import math
import os
import tempfile
import time

import pytest

from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.public.mix_conversion_backend import _convert_sync, _convert_async, _resolve_backend
from kinocut_sound.public.mix_conversion_shape import conversion_shape

pytestmark = pytest.mark.skipif(os.name != "posix", reason="supplied mix requires POSIX descriptors")


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize(
    "source_rate,target_rate,frames",
    [
        (48000, 44100, 240),
        (48000, 24000, 5),
        (8000, 96000, 1),
        (44100, 48000, 101),
    ],
)
def test_real_guarded_half_and_short_frames(asynchronous, source_rate, target_rate, frames):
    data = pcm_to_wav(array("h", [1000, -500] * frames), sample_rate_hz=source_rate, channel_count=2)
    shape = conversion_shape(frames, source_rate, target_rate, 2)
    with tempfile.TemporaryFile() as raw:
        args = (data, shape, raw, _resolve_backend(), time.monotonic() + 10)
        result = asyncio.run(_convert_async(*args)) if asynchronous else _convert_sync(*args)
    output, rate, channels = decode_pcm_wav(result.wav_bytes)
    assert rate == target_rate and channels == 2 and len(output) == 2 * shape.target_frames
    assert result.raw_frames in (shape.raw_min, shape.raw_max)
    assert all(abs(right + left / 2) <= 1 for left, right in zip(output[::2], output[1::2], strict=True))


@pytest.mark.parametrize("frequency", [1000, 15000])
def test_passband_and_alias_rejection(frequency):
    source = array("h", (round(12000 * math.sin(2 * math.pi * frequency * i / 48000)) for i in range(48000)))
    data = pcm_to_wav(source, sample_rate_hz=48000)
    shape = conversion_shape(48000, 48000, 16000, 1)
    with tempfile.TemporaryFile() as raw:
        result = _convert_sync(data, shape, raw, _resolve_backend(), time.monotonic() + 10)
    pcm, _, _ = decode_pcm_wav(result.wav_bytes)
    middle = pcm[512:-512]
    ratio = math.sqrt(sum(value * value for value in middle) / len(middle)) / (12000 / math.sqrt(2))
    if frequency == 1000:
        assert abs(ratio - 1) < 0.005
    else:
        assert ratio < 0.001


@pytest.mark.parametrize("asynchronous", [False, True])
def test_same_rate_requires_no_backend(asynchronous):
    data = pcm_to_wav(array("h", [10, 20, 30]), sample_rate_hz=48000)
    shape = conversion_shape(3, 48000, 48000, 1)
    with tempfile.TemporaryFile() as raw:
        args = (data, shape, raw, None, time.monotonic() + 1)
        result = asyncio.run(_convert_async(*args)) if asynchronous else _convert_sync(*args)
        assert raw.tell() == 0
    assert result.wav_bytes is data and result.raw_frames == 3
