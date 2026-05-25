"""Audio attachment operations for the FFmpeg engine."""

from __future__ import annotations

import warnings as _warnings

from .defaults import DEFAULT_AUDIO_BITRATE
from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _has_audio,
    _movflags_args,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value, _run_ffprobe_json
from .audio_guardrails import validate_audio_mix
from .errors import MCPVideoError
from .models import EditResult


def _build_audio_filters(volume: float, fade_in: float, fade_out: float, duration: float) -> list[str]:
    """Build audio filter strings for volume and fade effects."""
    filters: list[str] = []
    if volume != 1.0:
        filters.append(f"volume={_escape_ffmpeg_filter_value(str(volume))}")
    if fade_in > 0:
        filters.append(f"afade=t=in:st=0:d={_escape_ffmpeg_filter_value(str(fade_in))}")
    if fade_out > 0:
        fade_start = max(0.0, duration - fade_out)
        filters.append(
            f"afade=t=out:st={_escape_ffmpeg_filter_value(str(fade_start))}:"
            f"d={_escape_ffmpeg_filter_value(str(fade_out))}"
        )
    return filters


def _build_add_audio_args(
    video_path: str,
    audio_path: str,
    filters: list[str],
    mix: bool,
    start_time: float | None,
    source_has_audio: bool,
    output: str,
) -> list[str]:
    """Construct FFmpeg argument list for add_audio operation."""
    if mix and source_has_audio:
        af = ",".join(filters) if filters else "anull"
        delay = ""
        if start_time:
            safe_delay = _escape_ffmpeg_filter_value(str(int(start_time * 1000)))
            delay = f"[1:a]adelay={safe_delay}|{safe_delay},"
        filter_complex = f"[0:a]anull[a0];{delay}[1:a]{af}[a1];[a0][a1]amix=inputs=2:duration=longest[aout]"
        return [
            "-i",
            video_path,
            "-i",
            audio_path,
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            *_movflags_args(output),
            output,
        ]

    # Replace audio (or add if no existing audio)
    args = ["-i", video_path, "-i", audio_path]

    if start_time:
        safe_delay = _escape_ffmpeg_filter_value(str(int(start_time * 1000)))
        args.extend(["-filter_complex", f"[1:a]adelay={safe_delay}|{safe_delay}[a]"])
        args.extend(["-map", "0:v:0", "-map", "[a]"])
    else:
        args.extend(["-map", "0:v:0", "-map", "1:a:0"])

    if filters:
        args.extend(["-af", ",".join(filters)])

    args.extend(
        [
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            DEFAULT_AUDIO_BITRATE,
            "-shortest",
            *_movflags_args(output),
            output,
        ]
    )
    return args


def add_audio(
    video_path: str,
    audio_path: str,
    volume: float = 1.0,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    mix: bool = False,
    start_time: float | None = None,
    output_path: str | None = None,
) -> EditResult:
    """Add or replace audio track on a video."""
    video_path = _validate_input_path(video_path)
    audio_path = _validate_input_path(audio_path)
    output = output_path or _auto_output(video_path, "audio")
    _validate_output_path(output)

    video_info = probe(video_path)
    source_has_audio = _has_audio(_run_ffprobe_json(video_path))

    # --- Guardrails: audio mix validation ---
    # Validate volume first (hard constraint, no probe needed)
    if volume < 0.0:
        raise MCPVideoError(
            f"volume must be >= 0, got {volume}",
            error_type="validation_error",
            code="invalid_volume",
        )
    if volume > 1.0:
        _warnings.warn(
            f"[AUDIO GUARDRAIL] volume={volume} > 1.0. If source audio is already "
            f"near peak, this may cause digital clipping/distortion.",
            stacklevel=2,
        )
    # Validate timing/probe-based checks (best-effort, may fail for audio-only)
    try:
        audio_info = probe(audio_path)
        mix_warnings = validate_audio_mix(
            video_info, audio_info,
            volume=volume, start_time=start_time or 0.0,
        )
        for w in mix_warnings:
            _warnings.warn(f"[AUDIO GUARDRAIL] {w}", stacklevel=2)
    except Exception as e:
        _warnings.warn(f"[AUDIO GUARDRAIL] Could not validate audio mix: {e}", stacklevel=2)
    # --- End guardrails ---

    with _timed_operation() as timing:
        filters = _build_audio_filters(volume, fade_in, fade_out, video_info.duration)
        cmd = _build_add_audio_args(video_path, audio_path, filters, mix, start_time, source_has_audio, output)
        _run_ffmpeg(cmd)

    warnings = []
    if source_has_audio and not mix:
        warnings.append(
            "This operation will replace existing audio. Use mix=True to "
            "preserve source audio and listen before publishing."
        )

    return _build_edit_result(output, "add_audio", timing).model_copy(update={"warnings": warnings})
