"""Fade operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_media_timeline import _packet_extent, _source_identity, _timeline_error, _timestamp
from .engine_runtime_utils import (
    _build_edit_result,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .errors import MCPVideoError
from .models import EditResult


def fade(
    input_path: str,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    output_path: str | None = None,
    crf: int | None = None,
    preset: str | None = None,
) -> EditResult:
    """Add fade in/out effect to a video."""
    input_path = _validate_input_path(input_path)
    fade_in = _sanitize_ffmpeg_number(fade_in, "fade_in")
    fade_out = _sanitize_ffmpeg_number(fade_out, "fade_out")
    if fade_in <= 0 and fade_out <= 0:
        raise MCPVideoError("Specify fade_in and/or fade_out > 0", code="no_fade")

    output = output_path or _auto_output(input_path, "faded")
    _validate_output_path(output)
    identity = _source_identity(input_path)
    metadata = _run_ffprobe_json(input_path)
    start, duration = _packet_extent(input_path, "v:0")
    if _source_identity(input_path) != identity:
        raise _timeline_error("Source changed while measuring its timeline", "media_source_changed")
    container_start = _timestamp(metadata.get("format", {}).get("start_time")) or 0.0
    origin = start - container_start

    vf_parts: list[str] = []
    if fade_in > 0:
        safe_start = _escape_ffmpeg_filter_value(repr(origin))
        safe_duration = _escape_ffmpeg_filter_value(repr(fade_in))
        vf_parts.append(f"fade=t=in:st={safe_start}:d={safe_duration}")
    if fade_out > 0:
        fade_start = origin + max(0, duration - fade_out)
        safe_start = _escape_ffmpeg_filter_value(repr(fade_start))
        safe_duration = _escape_ffmpeg_filter_value(repr(fade_out))
        vf_parts.append(f"fade=t=out:st={safe_start}:d={safe_duration}")

    vf = ",".join(vf_parts)

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=staged,
                video_filter=vf,
                audio_codec="copy",
                crf=crf,
                preset=preset,
                extra=["-map", "0:v:0", "-map", "0:a:0?", "-fps_mode", "passthrough"],
            )
        )

        result = _build_edit_result(
            staged,
            "fade",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
