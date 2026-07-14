"""Deterministic linear crossfades between mono WAV clips."""

from __future__ import annotations

from array import array

from kinocut_sound.mix._errors import MIX_CROSSFADE_INVALID, mix_error
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav


def crossfade_pair(
    wav_a: bytes,
    wav_b: bytes,
    *,
    fade_seconds: float,
) -> bytes:
    """Return A then B with a linear equal-power-ish crossfade of ``fade_seconds``."""

    if fade_seconds <= 0:
        raise mix_error("fade_seconds must be positive", MIX_CROSSFADE_INVALID)
    samples_a, rate_a = parse_wav(wav_a)
    samples_b, rate_b = parse_wav(wav_b)
    if rate_a != rate_b:
        raise mix_error("crossfade requires matching sample rates", MIX_CROSSFADE_INVALID)
    fade_n = round(fade_seconds * rate_a)
    if fade_n <= 0:
        raise mix_error("fade window too short", MIX_CROSSFADE_INVALID)
    if len(samples_a) < fade_n or len(samples_b) < fade_n:
        raise mix_error("clips shorter than fade window", MIX_CROSSFADE_INVALID)

    out = array("h")
    # body of A without the trailing fade region
    out.extend(samples_a[: len(samples_a) - fade_n])
    for i in range(fade_n):
        t = i / float(fade_n)
        a = samples_a[len(samples_a) - fade_n + i]
        b = samples_b[i]
        # linear crossfade
        mixed = int((1.0 - t) * a + t * b)
        out.append(max(-32768, min(32767, mixed)))
    out.extend(samples_b[fade_n:])
    return pcm_to_wav(out, sample_rate_hz=rate_a)
