"""Private FFmpeg filtergraph builders for the governed audio-bed engine."""

from __future__ import annotations

import math
from typing import Any

from .audio_bed_validation import validation_error as _validation_error
from .defaults import (
    DEFAULT_AUDIO_BED_LOOP_MAX_PLAYS,
    DEFAULT_AUDIO_BED_TRUE_PEAK_DBTP,
    DEFAULT_LRA_TARGET,
)
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _sanitize_ffmpeg_number


def _n(value: Any, name: str) -> str:
    """Sanitize, then escape a numeric filter argument."""
    return _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(value, name)))


def _build_duck_filtergraph(*, music_volume: float, duck_threshold: float, duck_ratio: float, duck_attack: float, duck_release: float, fade_in: float, fade_out: float, target_duration: float, target_lufs: float) -> str:
    """Build the sidechain-duck + fade + loudnorm filtergraph (voice present)."""
    fade_start = max(0.0, target_duration - fade_out)
    vol, thr, rat = _n(music_volume, "music_volume"), _n(duck_threshold, "duck_threshold"), _n(duck_ratio, "duck_ratio")
    atk, rel, lufs = _n(duck_attack, "duck_attack"), _n(duck_release, "duck_release"), _n(target_lufs, "target_lufs")
    tp, lra = _n(DEFAULT_AUDIO_BED_TRUE_PEAK_DBTP, "true_peak"), _n(DEFAULT_LRA_TARGET, "lra")
    return "".join([
        f"[1:a]volume={vol}[bg];", f"[bg][0:a]sidechaincompress=threshold={thr}:ratio={rat}",
        f":attack={atk}:release={rel}[ducked];", f"[ducked]afade=t=in:st=0:d={_n(fade_in, 'fade_in')}",
        f",afade=t=out:st={_n(fade_start, 'fade_start')}:d={_n(fade_out, 'fade_out')}[faded];",
        "[0:a][faded]amix=inputs=2:duration=first:normalize=0[mixed];", f"[mixed]loudnorm=I={lufs}:TP={tp}:LRA={lra}[aout]",
    ])


def _build_no_duck_filtergraph(*, music_volume: float, fade_in: float, fade_out: float, target_duration: float, target_lufs: float, needs_pad: bool) -> str:
    """Build fade + loudnorm filtergraph for the no-voice case (no ducking)."""
    fade_start = max(0.0, target_duration - fade_out)
    vol, lufs = _n(music_volume, "music_volume"), _n(target_lufs, "target_lufs")
    tp, lra = _n(DEFAULT_AUDIO_BED_TRUE_PEAK_DBTP, "true_peak"), _n(DEFAULT_LRA_TARGET, "lra")
    pad = "apad," if needs_pad else ""
    return (
        f"[1:a]{pad}volume={vol}"
        f",afade=t=in:st=0:d={_n(fade_in, 'fade_in')}"
        f",afade=t=out:st={_n(fade_start, 'fade_start')}:d={_n(fade_out, 'fade_out')}"
        f",loudnorm=I={lufs}:TP={tp}:LRA={lra}[aout]"
    )


def _compute_loop_plays(bed_duration: float, target_duration: float, crossfade: float) -> int:
    """Return the bounded number of crossfaded bed plays needed for a target."""
    if bed_duration <= crossfade:
        raise _validation_error("loop_crossfade must be smaller than the bed duration", "invalid_loop_crossfade")
    plays = max(2, math.ceil((target_duration + crossfade) / (bed_duration - crossfade)))
    if plays > DEFAULT_AUDIO_BED_LOOP_MAX_PLAYS:
        raise _validation_error("bed is too short for the target duration under the loop cap", "loop_limit_exceeded")
    return plays


def _build_loop_filtergraph(bed_duration: float, target_duration: float, crossfade: float) -> tuple[str, int]:
    """Build a crossfaded loop graph for a short music bed."""
    plays = _compute_loop_plays(bed_duration, target_duration, crossfade)
    safe_bed, safe_xfade, safe_target = _n(bed_duration, "bed_duration"), _n(crossfade, "loop_crossfade"), _n(target_duration, "target_duration")
    labels = "".join(f"[s{i}]" for i in range(plays))
    parts = [f"[0:a]asplit={plays}{labels}"] + [f"[s{i}]atrim=0:{safe_bed},asetpts=PTS-STARTPTS[p{i}]" for i in range(plays)]
    previous = "p0"
    for index in range(1, plays):
        output = f"x{index}" if index < plays - 1 else "looped"
        parts.append(f"[{previous}][p{index}]acrossfade=d={safe_xfade}[{output}]")
        previous = output
    parts.append(f"[{previous}]atrim=0:{safe_target},asetpts=PTS-STARTPTS[out]")
    return ";".join(parts), plays
