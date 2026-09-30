"""Basic edit operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _atomic_output, _build_ffmpeg_cmd, _sanitize_ffmpeg_number
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .models import EditResult
from .validation import MAX_TRIM_TIME_TEXT_LENGTH


def _time_to_seconds(value: str | float) -> float:
    """Convert a time string (HH:MM:SS or seconds) to float seconds."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise MCPVideoError(
            "Trim time must be numeric seconds or a time string",
            error_type="validation_error",
            code="invalid_parameter",
        )
    try:
        if isinstance(value, str):
            if len(value) > MAX_TRIM_TIME_TEXT_LENGTH:
                raise MCPVideoError(
                    "Trim time string is too long",
                    error_type="validation_error",
                    code="invalid_parameter",
                )
            value = value.strip()
            if ":" in value:
                parts = value.split(":")
                if len(parts) == 2:
                    minutes, seconds = parts
                    value = int(minutes) * 60 + float(seconds)
                elif len(parts) == 3:
                    hours, minutes, seconds = parts
                    value = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return _sanitize_ffmpeg_number(value, "trim time")
    except OverflowError:
        raise MCPVideoError(
            "Trim time must be a finite number",
            error_type="validation_error",
            code="invalid_parameter",
        ) from None


def _validate_trim_times(
    start: str | float,
    duration: str | float | None,
    end: str | float | None,
) -> float:
    """Validate and convert trim time parameters, returning the start time in seconds."""
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

    return start_sec


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
        accurate: Kept for compatibility. Both values use frame-accurate
            input seeking because this operation always re-encodes.
    """
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "trimmed")
    _validate_output_path(output)

    start_sec = _validate_trim_times(start, duration, end)

    prefix: list[str] = []
    if start:
        # Re-encoding uses FFmpeg's default accurate input seek.
        prefix.extend(["-ss", str(start)])
    prefix.extend(["-i", input_path])
    if duration:
        prefix.extend(["-t", str(duration)])
    elif end:
        # Input seeking rebases timestamps; convert the absolute endpoint.
        prefix.extend(["-t", str(_time_to_seconds(end) - start_sec)])

    with _atomic_output(output) as staged:
        _validate_output_path(staged)
        with _timed_operation() as timing:
            _run_ffmpeg(prefix + _build_ffmpeg_cmd(output_path=staged))
        result = _build_edit_result(staged, "trim", timing)

    return result.model_copy(update={"output_path": output})
