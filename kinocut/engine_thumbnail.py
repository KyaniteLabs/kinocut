"""Thumbnail/frame extraction operations for the FFmpeg engine."""

from __future__ import annotations

from .engine_edit import _time_to_seconds
from .errors import MCPVideoError, ValidationError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_probe import get_duration
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .models import ThumbnailResult


def thumbnail(
    input_path: str,
    timestamp: float | str | None = None,
    output_path: str | None = None,
) -> ThumbnailResult:
    """Extract a single frame from a video."""
    input_path = _validate_input_path(input_path)

    if timestamp is None:
        # Grab frame at 10% of video duration
        dur = get_duration(input_path)
        timestamp = dur * 0.1
    else:
        # Clamp to valid range
        dur = get_duration(input_path)
        try:
            requested_timestamp = _time_to_seconds(timestamp)
        except ValueError as exc:
            raise MCPVideoError(
                f"Invalid timestamp: '{timestamp}'. Expected seconds or HH:MM:SS format.",
                error_type="validation_error",
                code="invalid_parameter",
            ) from exc
        if dur > 0 and requested_timestamp >= dur:
            raise ValidationError(
                "timestamp",
                f"{requested_timestamp:.3f}s exceeds video duration {dur:.3f}s",
            )
        timestamp = requested_timestamp

    output = output_path or _auto_output(input_path, f"frame_{timestamp:.1f}s", ext=".jpg")
    _validate_output_path(output)

    _run_ffmpeg(
        [
            "-ss",
            str(timestamp),
            "-i",
            input_path,
            "-vframes",
            "1",
            "-q:v",
            "2",
            "-y",
            output,
        ]
    )

    return ThumbnailResult(
        frame_path=output,
        timestamp=timestamp,
    )
