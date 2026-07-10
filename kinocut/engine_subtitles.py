"""Subtitle burn-in operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_runtime_utils import (
    _build_edit_result,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult


def subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str = "FontSize=22,PrimaryColour=&Hffffff&,OutlineColour=&H000000&,Outline=2,Shadow=1",
) -> EditResult:
    """Burn subtitles (SRT/VTT) into a video."""
    input_path = _validate_input_path(input_path)
    subtitle_path = _validate_input_path(subtitle_path)
    _require_filter("subtitles", "Subtitle burn-in")
    output = output_path or _auto_output(input_path, "subtitled")
    _validate_output_path(output)

    # Escape special characters for FFmpeg subtitle filter path
    escaped_sub_path = _escape_ffmpeg_filter_value(subtitle_path)
    # force_style is ASS `Key=Value,Key=Value` syntax: its separators must stay
    # literal, so quote the whole value instead of escaping it. Quotes and
    # backslashes are never valid in ASS style overrides — strip them.
    sanitized_style = style.replace("\\", "").replace("'", "")

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=output,
                video_filter=f"subtitles={escaped_sub_path}:force_style='{sanitized_style}'",
                audio_codec="copy",
            )
        )

    return _build_edit_result(
        output,
        "subtitles",
        timing,
    )
