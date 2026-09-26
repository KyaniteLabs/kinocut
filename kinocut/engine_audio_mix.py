"""Layer several sounds on a video in one FFmpeg pass.

``add_audio(mix=True)`` re-encodes the whole soundtrack in AAC every time it adds
one sound. Layering a dozen voice clips and sound effects that way stacks a dozen
lossy generations: the coding noise builds up into an audible hiss over quiet
passages. ``mix_audio`` mixes every track in a single filter graph and encodes the
result once, with the picture stream-copied.
"""

from __future__ import annotations

import math

from .defaults import DEFAULT_AUDIO_MIX_BITRATE
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _has_audio, _movflags_args, _timed_operation
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _run_ffprobe_json,
    _validate_input_path,
    _validate_output_path,
)
from .limits import MAX_AUDIO_MIX_TRACKS, MAX_AUDIO_MIX_VOLUME
from .models import EditResult
from .paths import _auto_output

_TRACK_KEYS = {"path", "start", "volume", "fade_in", "fade_out"}
_STEREO_48K = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"


def _invalid(message: str, code: str = "invalid_parameter") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _number(track: dict, key: str, index: int, default: float, high: float) -> float:
    value = track.get(key, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise _invalid(f"tracks[{index}].{key} must be a finite number")
    if not 0 <= float(value) <= high:
        raise _invalid(f"tracks[{index}].{key} must be between 0 and {high:g}")
    return float(value)


def _validate_tracks(tracks: list[dict], duration: float) -> list[dict]:
    """Check each track and return it normalised: path validated, numbers defaulted."""
    if not isinstance(tracks, list) or not tracks:
        raise _invalid("tracks must be a non-empty list")
    if len(tracks) > MAX_AUDIO_MIX_TRACKS:
        raise _invalid(f"tracks may hold at most {MAX_AUDIO_MIX_TRACKS} sounds")
    clean = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict) or not isinstance(track.get("path"), str):
            raise _invalid(f"tracks[{index}] must be a dict with a 'path' string")
        if set(track) - _TRACK_KEYS:
            raise _invalid(f"tracks[{index}] has unknown keys; allowed: {sorted(_TRACK_KEYS)}")
        clean.append(
            {
                "path": _validate_input_path(track["path"]),
                "start": _number(track, "start", index, 0.0, duration),
                "volume": _number(track, "volume", index, 1.0, MAX_AUDIO_MIX_VOLUME),
                "fade_in": _number(track, "fade_in", index, 0.0, duration),
                "fade_out": _number(track, "fade_out", index, 0.0, duration),
            }
        )
    return clean


def _track_chain(input_index: int, track: dict) -> str:
    """Filter chain of one added sound: format, volume, fades, then its place on the timeline."""
    steps = [_STEREO_48K]
    if track["volume"] != 1.0:
        steps.append(f"volume={_escape_ffmpeg_filter_value(repr(track['volume']))}")
    if track["fade_in"] > 0:
        steps.append(f"afade=t=in:st=0:d={_escape_ffmpeg_filter_value(repr(track['fade_in']))}")
    if track["fade_out"] > 0:
        # The fade ends where the sound ends; areverse keeps it exact without probing each file.
        fade = _escape_ffmpeg_filter_value(repr(track["fade_out"]))
        steps += ["areverse", f"afade=t=in:st=0:d={fade}", "areverse"]
    if track["start"] > 0:
        delay = _escape_ffmpeg_filter_value(str(round(track["start"] * 1000)))
        steps.append(f"adelay={delay}|{delay}")
    return f"[{input_index}:a:0]" + ",".join(steps) + f"[t{input_index}]"


def _build_mix_args(
    video_path: str, tracks: list[dict], keep_source: bool, duration: float, output: str, bitrate: str
) -> list[str]:
    """FFmpeg arguments: every sound summed at unity in one graph, one AAC encode, picture copied."""
    args = ["-i", video_path]
    for track in tracks:
        args += ["-i", track["path"]]
    chains = [_track_chain(i + 1, track) for i, track in enumerate(tracks)]
    labels = [f"[t{i + 1}]" for i in range(len(tracks))]
    if keep_source:
        chains.insert(0, f"[0:a:0]{_STEREO_48K}[t0]")
        labels.insert(0, "[t0]")
    length = _escape_ffmpeg_filter_value(f"{duration:.6f}")
    mix = f"amix=inputs={len(labels)}:duration=longest:normalize=0," if len(labels) > 1 else ""
    chains.append("".join(labels) + f"{mix}apad,atrim=0:{length}[aout]")
    return [
        *args,
        "-filter_complex",
        ";".join(chains),
        "-map",
        "0:v:0",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        bitrate,
        "-t",
        length,
        *_movflags_args(output),
        output,
    ]


def mix_audio(
    video_path: str,
    tracks: list[dict],
    output_path: str | None = None,
    *,
    keep_source: bool = True,
    audio_bitrate: str = DEFAULT_AUDIO_MIX_BITRATE,
) -> EditResult:
    """Layer sounds on a video in one pass and encode the soundtrack once.

    Each track is ``{"path", "start"=0, "volume"=1, "fade_in"=0, "fade_out"=0}``:
    ``start`` places the sound on the video timeline (seconds), ``volume`` is a
    linear gain (0 to 4). The video's own sound stays under the tracks unless
    ``keep_source`` is false. Tracks sum at unity (no 1/n attenuation); the output
    keeps the video's duration, with the picture stream-copied.
    """
    video_path = _validate_input_path(video_path)
    output = output_path or _auto_output(video_path, "mixed")
    _validate_output_path(output)
    if not isinstance(audio_bitrate, str) or not audio_bitrate.removesuffix("k").isdigit():
        raise _invalid("audio_bitrate must look like '256k'")
    duration = probe(video_path).duration
    if not duration or duration <= 0:
        raise _invalid("video has no measurable duration", "invalid_media_duration")
    clean = _validate_tracks(tracks, duration)
    keep = bool(keep_source) and _has_audio(_run_ffprobe_json(video_path))
    with _timed_operation() as timing:
        _run_ffmpeg(_build_mix_args(video_path, clean, keep, duration, output, audio_bitrate))
    return _build_edit_result(output, "mix_audio", timing)
