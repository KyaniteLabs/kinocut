"""Thumbnail/frame extraction operations for the FFmpeg engine."""

from __future__ import annotations
import os
import shutil

from .engine_edit import _time_to_seconds
from .errors import MCPVideoError, ValidationError
from .ffmpeg_helpers import _validate_input_path
from .engine_probe import get_duration
from .paths import _auto_output
from .ffmpeg_helpers import _atomic_output, _open_staged_writer, _run_ffmpeg
from .models import ThumbnailResult


def thumbnail(
    input_path: str,
    timestamp: float | str | None = None,
    output_path: str | None = None,
    smart: bool = True,
) -> ThumbnailResult:
    """Extract a single frame from a video.

    When smart=True and timestamp is None, uses NIMA to find the most
    aesthetically pleasing frame instead of defaulting to 10% of duration.
    Falls back to 10% if NIMA is unavailable.
    """
    input_path = _validate_input_path(input_path)

    if timestamp is None:
        if smart:
            from .aesthetic.smart_thumbnail import selected_frame

            suffix = os.path.splitext(output_path)[1].lower() if output_path else ".jpg"
            with selected_frame(input_path, suffix=suffix) as (timestamp, candidate):
                if candidate is not None and os.path.splitext(candidate)[1] == suffix:
                    output = output_path or _auto_output(input_path, f"frame_{timestamp:.1f}s", ext=".jpg")
                    with (
                        _atomic_output(output) as staged,
                        _open_staged_writer(staged) as dest,
                        open(candidate, "rb") as frame,
                    ):
                        shutil.copyfileobj(frame, dest)
                    return ThumbnailResult(frame_path=output, timestamp=timestamp)
        if timestamp is None:
            # Default: 10% of video duration
            dur = get_duration(input_path)
            timestamp = dur * 0.1
    else:
        # Clamp to valid range
        dur = get_duration(input_path)
        try:
            requested_timestamp = _time_to_seconds(timestamp)
        except ValueError as exc:
            raise MCPVideoError(
                "Invalid timestamp. Expected seconds or HH:MM:SS format.",
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
    with _atomic_output(output) as staged:
        _run_ffmpeg(["-ss", str(timestamp), "-i", input_path, "-vframes", "1", "-q:v", "2", "-y", staged])

    return ThumbnailResult(
        frame_path=output,
        timestamp=timestamp,
    )
