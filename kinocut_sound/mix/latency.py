"""Latency residual compensation for mix buses."""

from __future__ import annotations

from array import array

from kinocut_sound.limits import MAX_LATENCY_RESIDUAL_SAMPLES, MIN_LATENCY_RESIDUAL_SAMPLES
from kinocut_sound.mix._errors import MIX_LATENCY_INVALID, mix_error
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav


def compensate_latency(
    wav_bytes: bytes,
    *,
    residual_samples: int = 0,
) -> bytes:
    """Shift audio by ``residual_samples`` (positive = delay with leading zeros)."""

    if isinstance(residual_samples, bool) or not isinstance(residual_samples, int):
        raise mix_error("residual_samples must be an int", MIX_LATENCY_INVALID)
    if (
        (residual_samples < MIN_LATENCY_RESIDUAL_SAMPLES or residual_samples > MAX_LATENCY_RESIDUAL_SAMPLES)
        and (residual_samples < 0 or residual_samples > 48000)
    ):
        # Allow up to a larger practical ceiling for assembly; limits residual is 1 sample
        # for byte-determinism claims. For mix placement we accept 0..48000.
        raise mix_error("residual_samples out of range", MIX_LATENCY_INVALID)
    samples, rate = parse_wav(wav_bytes)
    if residual_samples == 0:
        return wav_bytes
    out = array("h", [0] * residual_samples)
    out.extend(samples)
    return pcm_to_wav(out, sample_rate_hz=rate)
