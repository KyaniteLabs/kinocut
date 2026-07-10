"""Basic edit operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .models import EditResult


def _time_to_seconds(value: str | float) -> float:
    """Convert a time string (HH:MM:SS or seconds) to float seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    value = value.strip()
    # Handle HH:MM:SS or MM:SS
    if ":" in value:
        parts = value.split(":")
        if len(parts) == 2:
            m, s = parts
            return int(m) * 60 + float(s)
        elif len(parts) == 3:
            h, m, s = parts
            return int(h) * 3600 + int(m) * 60 + float(s)
    return float(value)


def trim(
    input_path: str,
    start: str | float = 0,
    duration: str | float | None = None,
    end: str | float | None = None,
    output_path: str | None = None,
    accurate: bool = False,
) -> EditResult:
    """Trim a video by start time and duration or end time.

    Args:
        accurate: When True, place ``-ss`` after ``-i`` for frame-accurate
            seeking (slower).  Default False uses input seeking (fast).
    """
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "trimmed")
    _validate_output_path(output)

    # Validate time values
    try:
        start_sec = _time_to_seconds(start)
    except ValueError:
        raise MCPVideoError(
            f"Invalid start time: '{start}'. Expected seconds or HH:MM:SS format.",
            error_type="validation_error",
            code="invalid_parameter",
        ) from None
    if start_sec < 0:
        raise MCPVideoError(
            f"Start time must be non-negative, got {start_sec}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    if duration is not None:
        try:
            dur_sec = _time_to_seconds(duration)
        except ValueError:
            raise MCPVideoError(
                f"Invalid duration: '{duration}'. Expected seconds or HH:MM:SS format.",
                error_type="validation_error",
                code="invalid_parameter",
            ) from None
        if dur_sec <= 0:
            raise MCPVideoError(
                f"Duration must be positive, got {dur_sec}",
                error_type="validation_error",
                code="invalid_parameter",
            )

    if end is not None:
        try:
            end_sec = _time_to_seconds(end)
        except ValueError:
            raise MCPVideoError(
                f"Invalid end time: '{end}'. Expected seconds or HH:MM:SS format.",
                error_type="validation_error",
                code="invalid_parameter",
            ) from None
        if end_sec <= 0:
            raise MCPVideoError(
                f"End time must be positive, got {end_sec}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        if end_sec <= start_sec:
            raise MCPVideoError(
                f"End time ({end_sec}s) must be greater than start time ({start_sec}s)",
                error_type="validation_error",
                code="invalid_parameter",
            )

    prefix: list[str] = []
    if not accurate and start:
        # Input seeking — fast but may land on nearest keyframe
        prefix.extend(["-ss", str(start)])
    prefix.extend(["-i", input_path])
    if accurate and start:
        # Output seeking — frame accurate but slower
        prefix.extend(["-ss", str(start)])
    if duration:
        prefix.extend(["-t", str(duration)])
    elif end:
        prefix.extend(["-to", str(end)])

    with _timed_operation() as timing:
        _run_ffmpeg(prefix + _build_ffmpeg_cmd(output_path=output))

    return _build_edit_result(
        output,
        "trim",
        timing,
    )
