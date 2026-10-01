"""Layer several sounds on a video in one FFmpeg pass.

``add_audio(mix=True)`` re-encodes the whole soundtrack in AAC every time it adds
one sound. Layering a dozen voice clips and sound effects that way stacks a dozen
lossy generations: the coding noise builds up into an audible hiss over quiet
passages. ``mix_audio`` mixes every track in a single filter graph and encodes the
result once, with the picture stream-copied.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .defaults import DEFAULT_AUDIO_MIX_BITRATE, DEFAULT_AUDIO_MIX_SAMPLE_RATE, DEFAULT_AUDIO_MIX_TRACK_VOLUME
from .engine_media_timeline import _packet_extent, _primary_audio_timeline
from .engine_audio_validation import _audio_number, _run_audio_ffmpeg
from .engine_audio_normalize_output import _validate_normalized_output
from .engine_runtime_utils import _build_edit_result, _get_video_stream, _has_audio, _movflags_args, _timed_operation
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _atomic_output,
    _escape_ffmpeg_filter_value,
    _run_command,
    _run_ffmpeg,
    _run_ffprobe_json,
    _validate_input_path,
    _validate_output_path,
)
from .limits import (
    MAX_AUDIO_MIX_TRACKS,
    MAX_AUDIO_MIX_VOLUME,
    MIN_AUDIO_MIX_BITRATE_KBPS,
    MAX_AUDIO_MIX_BITRATE_KBPS,
    MAX_VIDEO_DURATION,
    MAX_AUDIO_MIX_TIMELINE_METADATA_BYTES,
    MAX_AUDIO_MIX_TIMELINE_PACKETS,
)
from .models import EditResult
from .paths import _auto_output

_TRACK_KEYS = {"path", "start", "volume", "fade_in", "fade_out"}
_STEREO_FORMAT = "aformat=sample_fmts=fltp:channel_layouts=stereo"
_STEREO_48K = f"aresample={DEFAULT_AUDIO_MIX_SAMPLE_RATE},{_STEREO_FORMAT}"
_SOURCE_STEREO = f"aresample={DEFAULT_AUDIO_MIX_SAMPLE_RATE}:async=1:first_pts=0,{_STEREO_FORMAT}"


def _invalid(message: str, code: str = "invalid_parameter") -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)


def _packet_timeline(path: str) -> tuple[float, float]:
    """Measure primary-picture presentation extent, including VFR B frames."""
    return _packet_extent(
        path,
        "v:0",
        runner=_run_command,
        packet_limit=MAX_AUDIO_MIX_TIMELINE_PACKETS,
        metadata_limit=MAX_AUDIO_MIX_TIMELINE_METADATA_BYTES,
    )


def _picture_timeline(path: str, raw: dict) -> tuple[float, float]:
    """Use packet presentation ends: stream.duration may describe decode extent."""
    if _get_video_stream(raw) is None:
        raise _invalid("mix_audio requires a video stream", "missing_video_stream")
    start, duration = _packet_timeline(path)
    if not math.isfinite(start) or not math.isfinite(duration) or not 0 < duration <= MAX_VIDEO_DURATION:
        raise _invalid("video has no supported measurable duration", "invalid_media_duration")
    return start, duration


def _number(track: dict, key: str, index: int, default: float, high: float) -> float:
    return _audio_number(track.get(key, default), f"tracks[{index}].{key}", 0, high)


def _validate_tracks(tracks: list[dict], duration: float) -> list[dict]:
    """Check each track and return it normalised: path validated, numbers defaulted."""
    if not isinstance(tracks, list) or not tracks:
        raise _invalid("tracks must be a non-empty list")
    if len(tracks) > MAX_AUDIO_MIX_TRACKS:
        raise _invalid(f"tracks may hold at most {MAX_AUDIO_MIX_TRACKS} sounds")
    clean = []
    durations = {}
    for index, track in enumerate(tracks):
        if not isinstance(track, dict) or not isinstance(track.get("path"), str):
            raise _invalid(f"tracks[{index}] must be a dict with a 'path' string")
        if set(track) - _TRACK_KEYS:
            raise _invalid(f"tracks[{index}] has unknown keys; allowed: {sorted(_TRACK_KEYS)}")
        path = _validate_input_path(track["path"])
        start = _number(track, "start", index, 0.0, duration)
        if start >= duration:
            raise _invalid(f"tracks[{index}].start must precede the end of the video")
        if path not in durations:
            durations[path] = _primary_audio_timeline(path, _run_ffprobe_json(path))[1]
        audio_duration = durations[path]
        if not audio_duration or not math.isfinite(audio_duration) or audio_duration <= 0:
            raise _invalid(f"tracks[{index}] has no measurable audio duration", "invalid_media_duration")
        clean.append(
            {
                "path": path,
                "duration": min(audio_duration, duration - start),
                "start": start,
                "volume": _number(track, "volume", index, DEFAULT_AUDIO_MIX_TRACK_VOLUME, MAX_AUDIO_MIX_VOLUME),
                "fade_in": _number(track, "fade_in", index, 0.0, duration),
                "fade_out": _number(track, "fade_out", index, 0.0, duration),
            }
        )
    return clean


def _track_chain(input_index: int, track: dict) -> str:
    """Filter chain of one added sound: format, volume, fades, then its place on the timeline."""
    length = _escape_ffmpeg_filter_value(repr(track["duration"]))
    steps = [f"atrim=duration={length}", "asetpts=PTS-STARTPTS", _STEREO_48K]
    if track["volume"] != 1.0:
        steps.append(f"volume={_escape_ffmpeg_filter_value(repr(track['volume']))}")
    if track["fade_in"] > 0:
        steps.append(f"afade=t=in:st=0:d={_escape_ffmpeg_filter_value(repr(track['fade_in']))}")
    if track["fade_out"] > 0:
        fade = min(track["fade_out"], track["duration"])
        fade_start = _escape_ffmpeg_filter_value(repr(track["duration"] - fade))
        steps.append(f"afade=t=out:st={fade_start}:d={_escape_ffmpeg_filter_value(repr(fade))}")
    if track["start"] > 0:
        delay = _escape_ffmpeg_filter_value(str(round(track["start"] * DEFAULT_AUDIO_MIX_SAMPLE_RATE)))
        steps.append(f"adelay={delay}S:all=1")
    return f"[{input_index}:a:0]" + ",".join(steps) + f"[t{input_index}]"


def _build_mix_args(
    video_path: str,
    tracks: list[dict],
    keep_source: bool,
    duration: float,
    output: str,
    bitrate: str,
    *,
    video_start: float = 0.0,
) -> list[str]:
    """FFmpeg arguments: every sound summed at unity in one graph, one AAC encode, picture copied."""
    args = ["-xerror", "-copyts", "-itsoffset", str(-video_start), "-i", video_path]
    for track in tracks:
        args += ["-t", str(track["duration"]), "-i", track["path"]]
    chains = [_track_chain(i + 1, track) for i, track in enumerate(tracks)]
    labels = [f"[t{i + 1}]" for i in range(len(tracks))]
    if keep_source:
        chains.insert(0, f"[0:a:0]{_SOURCE_STEREO}[t0]")
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
    linear gain (0 to 4). Fades apply to the audible segment,
    clipped at the video end, without buffering whole tracks. The video's own sound stays under the tracks unless
    ``keep_source`` is false. Tracks sum at unity (no 1/n attenuation); the output
    keeps the primary picture's duration and relative source-audio timing, with
    picture stream-copied. A bounded audio decode validates staging before publication.
    """
    video_path = _validate_input_path(video_path)
    output = output_path or _auto_output(video_path, "mixed")
    if not isinstance(audio_bitrate, str) or not re.fullmatch(r"[0-9]{1,3}k", audio_bitrate):
        raise _invalid("audio_bitrate must look like '256k'")
    if not isinstance(keep_source, bool):
        raise _invalid("keep_source must be a boolean")
    rate = int(audio_bitrate.removesuffix("k"))
    if not MIN_AUDIO_MIX_BITRATE_KBPS <= rate <= MAX_AUDIO_MIX_BITRATE_KBPS or not audio_bitrate.endswith("k"):
        raise _invalid(
            f"audio_bitrate must be between '{MIN_AUDIO_MIX_BITRATE_KBPS}k' and '{MAX_AUDIO_MIX_BITRATE_KBPS}k'"
        )
    raw = _run_ffprobe_json(video_path)
    video_start, duration = _picture_timeline(video_path, raw)
    clean = _validate_tracks(tracks, duration)
    _validate_output_path(output)
    keep = keep_source and _has_audio(raw)
    with _atomic_output(output) as staged:
        _validate_output_path(staged)
        with _timed_operation() as timing:
            _run_audio_ffmpeg(
                _build_mix_args(video_path, clean, keep, duration, staged, audio_bitrate, video_start=video_start),
                runner=_run_ffmpeg,
            )
            _validate_normalized_output(staged, "aac", audio_only=True)
        result = _build_edit_result(staged, "mix_audio", timing, format=Path(output).suffix.lstrip("."))
    return result.model_copy(
        update={
            "output_path": output,
            "warnings": ["Tracks sum at unity without normalization and may clip. Listen before publishing."],
        }
    )
