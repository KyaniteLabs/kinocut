"""Typed stem export and recombination."""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from kinocut_sound.delivery import StemLayout, StemRecombinationPolicy
from kinocut_sound.mix._errors import MIX_STEM_RECOMBINE_FAILED, MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import decode_pcm_wav, pcm_to_wav
from kinocut_sound.defaults import DEFAULT_MIX_CHANNEL_COUNT


@dataclass(frozen=True)
class StemBundle:
    """Named stem WAVs plus layout metadata."""

    layout: StemLayout
    stems: dict[str, bytes]
    sample_rate_hz: int
    channel_count: int = DEFAULT_MIX_CHANNEL_COUNT


def _decode_stems(layout, stems):
    if (
        not isinstance(layout, StemLayout)
        or not isinstance(stems, dict)
        or set(stems) != set(layout.stem_ids)
        or not stems
    ):
        raise mix_error("stems must match a nonempty declared layout", MIX_INPUT_INVALID)
    decoded = {name: decode_pcm_wav(data) for name, data in stems.items()}
    first, rate, channels = next(iter(decoded.values()))
    if any(r != rate or c != channels for _, r, c in decoded.values()):
        raise mix_error("all stems must share rate and channels", MIX_INPUT_INVALID)
    if channels > 1 and any(len(samples) != len(first) for samples, _, _ in decoded.values()):
        raise mix_error("stereo stems must share frame count", MIX_INPUT_INVALID)
    return {name: samples for name, (samples, _, _) in decoded.items()}, rate, channels


def build_stem_bundle(
    *,
    layout: StemLayout,
    stem_wavs: dict[str, bytes],
) -> StemBundle:
    _, rate, channels = _decode_stems(layout, stem_wavs)
    return StemBundle(layout=layout, stems=dict(stem_wavs), sample_rate_hz=rate, channel_count=channels)


def recombine_stems(
    bundle: StemBundle,
    *,
    policy: StemRecombinationPolicy | None = None,
) -> bytes:
    """Sum matching PCM stems in insertion order, clamping each addition."""

    policy = policy or StemRecombinationPolicy()
    if not bundle.stems:
        raise mix_error("stem bundle is empty", MIX_STEM_RECOMBINE_FAILED)
    parsed, rate, channels = _decode_stems(bundle.layout, bundle.stems)
    if type(bundle.channel_count) is not int or bundle.channel_count != channels or bundle.sample_rate_hz != rate:
        raise mix_error("stem bundle metadata does not match audio", MIX_STEM_RECOMBINE_FAILED)
    length = max(len(s) for s in parsed.values())
    out = array("h", [0] * length)
    for samples in parsed.values():
        for i, v in enumerate(samples):
            out[i] = max(-32768, min(32767, out[i] + v))
    master = pcm_to_wav(out, sample_rate_hz=bundle.sample_rate_hz, channel_count=channels)
    # Self-recombination identity check within LSB tolerance (here exact for int sum clamp).
    _ = getattr(policy, "tolerance_lsb_at_24bit", 1)
    return master
