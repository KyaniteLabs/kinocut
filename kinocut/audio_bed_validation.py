"""Shared parameter and path validation for the audio-bed engine."""

from __future__ import annotations

import math
import os

from .errors import MCPVideoError
from .limits import (
    MAX_AUDIO_BED_DUCK_ATTACK_MS,
    MAX_AUDIO_BED_DUCK_RATIO,
    MAX_AUDIO_BED_DUCK_RELEASE_MS,
    MAX_AUDIO_BED_DUCK_THRESHOLD,
    MAX_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
    MAX_AUDIO_BED_FADE_SECONDS,
    MAX_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
    MAX_AUDIO_BED_MUSIC_VOLUME,
    MAX_AUDIO_BED_TARGET_LUFS,
    MIN_AUDIO_BED_DUCK_ATTACK_MS,
    MIN_AUDIO_BED_DUCK_RATIO,
    MIN_AUDIO_BED_DUCK_RELEASE_MS,
    MIN_AUDIO_BED_DUCK_THRESHOLD,
    MIN_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
    MIN_AUDIO_BED_FADE_SECONDS,
    MIN_AUDIO_BED_LOOP_CROSSFADE_SECONDS,
    MIN_AUDIO_BED_MUSIC_VOLUME,
    MIN_AUDIO_BED_TARGET_LUFS,
)


def validation_error(message: str, code: str = "invalid_parameter") -> MCPVideoError:
    """Return the stable typed validation error used by the engine."""

    return MCPVideoError(message, error_type="validation_error", code=code)


def _validate_numeric(value: float, name: str, lo: float, hi: float) -> float:
    """Validate a numeric parameter is a finite number in the closed range."""

    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise validation_error(f"{name} must be a finite number, got {value!r}", f"invalid_{name}")
    if value < lo or value > hi:
        raise validation_error(f"{name} must be between {lo} and {hi}, got {value}", f"invalid_{name}")
    return float(value)


def validate_audio_bed_params(
    *,
    loop: bool,
    loop_crossfade: float,
    fade_in: float,
    fade_out: float,
    duration_tolerance: float,
    target_lufs: float,
    duck_threshold: float,
    duck_ratio: float,
    duck_attack: float,
    duck_release: float,
    music_volume: float,
) -> None:
    """Validate every parameter before touching FFmpeg or the filesystem."""

    if type(loop) is not bool:
        raise validation_error("loop must be a boolean", "invalid_loop")

    bounds = (
        (loop_crossfade, "loop_crossfade", MIN_AUDIO_BED_LOOP_CROSSFADE_SECONDS, MAX_AUDIO_BED_LOOP_CROSSFADE_SECONDS),
        (fade_in, "fade_in", MIN_AUDIO_BED_FADE_SECONDS, MAX_AUDIO_BED_FADE_SECONDS),
        (fade_out, "fade_out", MIN_AUDIO_BED_FADE_SECONDS, MAX_AUDIO_BED_FADE_SECONDS),
        (target_lufs, "target_lufs", MIN_AUDIO_BED_TARGET_LUFS, MAX_AUDIO_BED_TARGET_LUFS),
        (duck_threshold, "duck_threshold", MIN_AUDIO_BED_DUCK_THRESHOLD, MAX_AUDIO_BED_DUCK_THRESHOLD),
        (duck_ratio, "duck_ratio", MIN_AUDIO_BED_DUCK_RATIO, MAX_AUDIO_BED_DUCK_RATIO),
        (duck_attack, "duck_attack", MIN_AUDIO_BED_DUCK_ATTACK_MS, MAX_AUDIO_BED_DUCK_ATTACK_MS),
        (duck_release, "duck_release", MIN_AUDIO_BED_DUCK_RELEASE_MS, MAX_AUDIO_BED_DUCK_RELEASE_MS),
        (music_volume, "music_volume", MIN_AUDIO_BED_MUSIC_VOLUME, MAX_AUDIO_BED_MUSIC_VOLUME),
        (
            duration_tolerance,
            "duration_tolerance",
            MIN_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
            MAX_AUDIO_BED_DURATION_TOLERANCE_SECONDS,
        ),
    )
    for value, name, minimum, maximum in bounds:
        _validate_numeric(value, name, minimum, maximum)


def reject_output_alias(output_path: str, inputs: tuple[str, ...]) -> None:
    """Reject output paths that resolve to or hardlink an input file."""

    output_resolved = os.path.realpath(output_path)
    for source in inputs:
        if output_resolved == os.path.realpath(source):
            raise validation_error("output path aliases an input", "invalid_output_path")
        if not os.path.exists(output_path):
            continue
        try:
            if os.path.samefile(output_path, source):
                raise validation_error("output path aliases an input", "invalid_output_path")
        except OSError:
            raise validation_error("cannot safely verify output identity", "invalid_output_path") from None
