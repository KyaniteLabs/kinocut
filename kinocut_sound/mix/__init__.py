"""``kinocut_sound.mix`` — assembly, mixing & stems (S9).

Public surface for timeline placement, crossfades, designed silence, bed
ducking, latency compensation, stem export/recombination, and authoritative
duration-proof mix rendering.
"""

from __future__ import annotations

from kinocut_sound.mix._errors import (
    MIX_CROSSFADE_INVALID,
    MIX_DURATION_MISMATCH,
    MIX_DUCKING_INVALID,
    MIX_INPUT_INVALID,
    MIX_LATENCY_INVALID,
    MIX_OVER_LIMIT,
    MIX_PLACEMENT_INVALID,
    MIX_STEM_RECOMBINE_FAILED,
    MIX_UNSAFE_PATH,
    MixError,
    mix_error,
)
from kinocut_sound.mix.crossfade import crossfade_pair
from kinocut_sound.mix.ducking import duck_bed_under_speech
from kinocut_sound.mix.latency import compensate_latency
from kinocut_sound.mix.placement import PlacedClip, PlacementPlan, place_clips
from kinocut_sound.mix.renderer import MixClip, MixRenderer, MixResult
from kinocut_sound.mix.seam import SeamEvent, SeamReport
from kinocut_sound.mix.silence import render_silence
from kinocut_sound.mix.stems import StemBundle, build_stem_bundle, recombine_stems

__version__ = "0.1.0"

__all__ = [
    "MIX_CROSSFADE_INVALID",
    "MIX_DUCKING_INVALID",
    "MIX_DURATION_MISMATCH",
    "MIX_INPUT_INVALID",
    "MIX_LATENCY_INVALID",
    "MIX_OVER_LIMIT",
    "MIX_PLACEMENT_INVALID",
    "MIX_STEM_RECOMBINE_FAILED",
    "MIX_UNSAFE_PATH",
    "MixClip",
    "MixError",
    "MixRenderer",
    "MixResult",
    "PlacedClip",
    "PlacementPlan",
    "SeamEvent",
    "SeamReport",
    "StemBundle",
    "build_stem_bundle",
    "compensate_latency",
    "crossfade_pair",
    "duck_bed_under_speech",
    "mix_error",
    "place_clips",
    "recombine_stems",
    "render_silence",
]
