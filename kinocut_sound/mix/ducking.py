"""Bed ducking under speech."""

from __future__ import annotations

from array import array

from kinocut_sound.limits import (
    MAX_DUCKING_ATTACK_MS,
    MAX_DUCKING_ATTENUATION_DB,
    MAX_DUCKING_RELEASE_MS,
    MIN_DUCKING_ATTENUATION_DB,
    MIN_DUCKING_TIME_MS,
)
from kinocut_sound.mix._errors import MIX_DUCKING_INVALID, mix_error
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav


def duck_bed_under_speech(
    speech_wav: bytes,
    bed_wav: bytes,
    *,
    attenuation_db: float = 12.0,
    attack_ms: float = 20.0,
    release_ms: float = 200.0,
) -> bytes:
    """Return bed audio with gain reduced where speech energy is present."""

    if not (MIN_DUCKING_ATTENUATION_DB < attenuation_db <= MAX_DUCKING_ATTENUATION_DB):
        raise mix_error("attenuation_db out of range", MIX_DUCKING_INVALID)
    if not (MIN_DUCKING_TIME_MS < attack_ms <= MAX_DUCKING_ATTACK_MS):
        raise mix_error("attack_ms out of range", MIX_DUCKING_INVALID)
    if not (MIN_DUCKING_TIME_MS < release_ms <= MAX_DUCKING_RELEASE_MS):
        raise mix_error("release_ms out of range", MIX_DUCKING_INVALID)

    speech, rate_s = parse_wav(speech_wav)
    bed, rate_b = parse_wav(bed_wav)
    if rate_s != rate_b:
        raise mix_error("speech and bed sample rates must match", MIX_DUCKING_INVALID)

    n = min(len(speech), len(bed))
    attack_n = max(1, int(rate_s * attack_ms / 1000.0))
    release_n = max(1, int(rate_s * release_ms / 1000.0))
    target = 10.0 ** (-attenuation_db / 20.0)
    gain = 1.0
    out = array("h")
    for i in range(n):
        level = abs(speech[i]) / 32768.0
        active = level > 0.02
        gain = (
            max(target, gain - (1.0 - target) / attack_n)
            if active
            else min(1.0, gain + (1.0 - target) / release_n)
        )
        sample = int(bed[i] * gain)
        out.append(max(-32768, min(32767, sample)))
    # preserve remaining bed after speech ends
    if len(bed) > n:
        out.extend(bed[n:])
    return pcm_to_wav(out, sample_rate_hz=rate_s)
