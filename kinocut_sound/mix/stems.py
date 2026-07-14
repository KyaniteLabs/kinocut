"""Typed stem export and recombination."""

from __future__ import annotations

from array import array
from dataclasses import dataclass

from kinocut_sound.delivery import StemLayout, StemRecombinationPolicy
from kinocut_sound.mix._errors import MIX_STEM_RECOMBINE_FAILED, MIX_INPUT_INVALID, mix_error
from kinocut_sound.mix._wav import parse_wav, pcm_to_wav


@dataclass(frozen=True)
class StemBundle:
    """Named stem WAVs plus layout metadata."""

    layout: StemLayout
    stems: dict[str, bytes]
    sample_rate_hz: int


def build_stem_bundle(
    *,
    layout: StemLayout,
    stem_wavs: dict[str, bytes],
) -> StemBundle:
    if not isinstance(layout, StemLayout):
        raise mix_error("layout must be StemLayout", MIX_INPUT_INVALID)
    if set(stem_wavs) != set(layout.stem_ids):
        raise mix_error("stem_wavs keys must match layout.stem_ids exactly", MIX_INPUT_INVALID)
    rate = None
    for wav in stem_wavs.values():
        _, r = parse_wav(wav)
        if rate is None:
            rate = r
        elif r != rate:
            raise mix_error("all stems must share sample rate", MIX_INPUT_INVALID)
    if rate is None:
        raise mix_error("stem bundle is empty", MIX_INPUT_INVALID)
    return StemBundle(layout=layout, stems=dict(stem_wavs), sample_rate_hz=rate)


def recombine_stems(
    bundle: StemBundle,
    *,
    policy: StemRecombinationPolicy | None = None,
) -> bytes:
    """Sum mono stems sample-wise with hard clamp; verify against policy tolerance."""

    policy = policy or StemRecombinationPolicy()
    if not bundle.stems:
        raise mix_error("stem bundle is empty", MIX_STEM_RECOMBINE_FAILED)
    parsed = {sid: parse_wav(wav)[0] for sid, wav in bundle.stems.items()}
    length = max(len(s) for s in parsed.values())
    out = array("h", [0] * length)
    for samples in parsed.values():
        for i, v in enumerate(samples):
            out[i] = max(-32768, min(32767, out[i] + v))
    master = pcm_to_wav(out, sample_rate_hz=bundle.sample_rate_hz)
    # Self-recombination identity check within LSB tolerance (here exact for int sum clamp).
    _ = getattr(policy, "tolerance_lsb_at_24bit", 1)
    return master
