"""Deterministic linear crossfades between matching PCM WAV clips."""

from __future__ import annotations

from array import array

from kinocut_sound.mix._errors import MIX_CROSSFADE_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav


def crossfade_pair(
    wav_a: bytes,
    wav_b: bytes,
    *,
    fade_seconds: float,
) -> bytes:
    """Return A then B with a linear, channel-linked crossfade."""

    if fade_seconds <= 0:
        raise mix_error("fade_seconds must be positive", MIX_CROSSFADE_INVALID)
    samples_a, rate_a, channels = decode_pcm_wav(wav_a)
    samples_b, rate_b, channels_b = decode_pcm_wav(wav_b)
    if rate_a != rate_b or channels != channels_b:
        raise mix_error("crossfade requires matching rates and channels", MIX_CROSSFADE_INVALID)
    fade_n = round(fade_seconds * rate_a)
    if fade_n <= 0:
        raise mix_error("fade window too short", MIX_CROSSFADE_INVALID)
    if len(samples_a) < fade_n * channels or len(samples_b) < fade_n * channels:
        raise mix_error("clips shorter than fade window", MIX_CROSSFADE_INVALID)

    out = array("h")
    # body of A without the trailing fade region
    out.extend(samples_a[: len(samples_a) - fade_n * channels])
    for i in range(fade_n):
        t = i / float(fade_n)
        for channel in range(channels):
            a = samples_a[len(samples_a) - fade_n * channels + i * channels + channel]
            b = samples_b[i * channels + channel]
            mixed = int((1.0 - t) * a + t * b)
            out.append(max(-32768, min(32767, mixed)))
    out.extend(samples_b[fade_n * channels :])
    return pcm_to_wav(out, sample_rate_hz=rate_a, channel_count=channels)
