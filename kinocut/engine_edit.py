"""Basic edit operations for the FFmpeg engine."""

from __future__ import annotations

from collections.abc import Callable

from .ffmpeg_helpers import _build_ffmpeg_cmd, _format_ffmpeg_number, _sanitize_ffmpeg_number
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_runtime_utils import _movflags_args, _transactional_edit
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg_with_progress
from .errors import CodecError, MCPVideoError, ProcessingError
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
            "start is not a valid time. Expected seconds or HH:MM:SS format.",
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
                "duration is not a valid time. Expected seconds or HH:MM:SS format.",
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
                "end is not a valid time. Expected seconds or HH:MM:SS format.",
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
    on_progress: Callable[[float], None] | None = None,
    *,
    stream_copy: bool = False,
) -> EditResult:
    """Trim a video by start time and duration or end time.

    Args:
        accurate: Kept for compatibility. Both values re-encode frame-accurately
            unless stream_copy is explicitly enabled.
        on_progress: Called with the render's percent complete (0-100).
        stream_copy: Copy compressed streams without re-encoding. Cut boundaries
            can shift to keyframes; incompatible output containers are refused.
    """
    if not isinstance(stream_copy, bool):
        raise MCPVideoError("stream_copy must be a boolean", error_type="validation_error", code="invalid_parameter")
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "trimmed")
    _validate_output_path(output)

    start_sec = _validate_trim_times(start, duration, end)

    prefix: list[str] = []
    if start_sec > 0:
        prefix.extend(["-ss", _format_ffmpeg_number(start_sec)])
    prefix.extend(["-i", input_path])
    clip_seconds: float | None = None
    if duration is not None and duration != "":
        clip_seconds = _time_to_seconds(duration)
        prefix.extend(["-t", _format_ffmpeg_number(clip_seconds)])
    elif end is not None and end != "":
        # Input seeking rebases timestamps; convert the absolute endpoint.
        clip_seconds = _time_to_seconds(end) - start_sec
        prefix.extend(["-t", _format_ffmpeg_number(clip_seconds)])
    elif on_progress is not None:
        from .engine_probe import probe

        clip_seconds = probe(input_path).duration - start_sec

    def render(staged: str) -> None:
        encode = (
            ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy", *_movflags_args(staged), staged]
            if stream_copy
            else _build_ffmpeg_cmd(output_path=staged)
        )
        try:
            _run_ffmpeg_with_progress(prefix + encode, clip_seconds, on_progress)
        except (CodecError, ProcessingError) as exc:
            if not stream_copy or (isinstance(exc, ProcessingError) and exc.returncode == -1):
                raise
            raise MCPVideoError(
                "Trim stream copy failed. Use a container compatible with the source codecs, "
                "or retry with stream_copy=False to re-encode.",
                error_type="processing_error",
                code="trim_stream_copy_failed",
            ) from None

    result = _transactional_edit(output, "trim", render)
    if stream_copy:
        warning = "Stream copy can snap cuts to nearby keyframes; the output may not match the requested boundaries."
        return result.model_copy(update={"warnings": [*result.warnings, warning]})
    return result
