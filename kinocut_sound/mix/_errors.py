"""Stable mix-leaf error codes."""

from __future__ import annotations

from kinocut_sound._errors import SoundContractError


MIX_INPUT_INVALID = "mix_input_invalid"
MIX_DURATION_MISMATCH = "mix_duration_mismatch"
MIX_STEM_RECOMBINE_FAILED = "mix_stem_recombine_failed"
MIX_PLACEMENT_INVALID = "mix_placement_invalid"
MIX_CROSSFADE_INVALID = "mix_crossfade_invalid"
MIX_DUCKING_INVALID = "mix_ducking_invalid"
MIX_LATENCY_INVALID = "mix_latency_invalid"
MIX_OVER_LIMIT = "mix_over_limit"
MIX_UNSAFE_PATH = "mix_unsafe_path"


class MixError(SoundContractError):
    """Bounded mix-assembly failure."""


def mix_error(message: str, code: str) -> MixError:
    return MixError(message, code=code)


def bounded_mix_error(message: str, code: str) -> MixError:
    return mix_error(message, code)
