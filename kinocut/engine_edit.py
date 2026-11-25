"""Basic edit operations for the FFmpeg engine."""

from __future__ import annotations

from collections.abc import Callable

from .ffmpeg_helpers import _build_ffmpeg_cmd, _format_ffmpeg_number, _sanitize_ffmpeg_number
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_runtime_utils import _build_edit_result, _movflags_args, _transactional_edit
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg, _run_ffmpeg_with_progress
from .errors import CodecError, MCPVideoError, ProcessingError
from .models import EditResult
from .validation import MAX_TRIM_TIME_TEXT_LENGTH


def _time_to_seconds(value: str | float, *, bpm=None, fps=30.0, offset_s=0.0, steps_per_bar=64) -> float:
    """Convert a time string (HH:MM:SS or seconds) to float seconds."""
    if bpm is not None:
        return _grid_trim_times(value, None, None, bpm, fps, offset_s, steps_per_bar)[0]
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


def _grid_trim_times(start, duration, end, bpm, fps, offset_s, steps_per_bar):
    from .music_grid import MusicalGrid

    try:
        grid = MusicalGrid(bpm, fps, offset_s, steps_per_bar)
        cuts = {}
        for name, value in (("start", start), ("end", end), ("duration", duration)):
            if value is None:
                continue
            if isinstance(value, str) and len(value) > MAX_TRIM_TIME_TEXT_LENGTH:
                raise ValueError
            if name == "start" and grid._parse(value) < 0:
                raise ValueError("Negative authored start")
            if name == "duration":
                relative = MusicalGrid(bpm, fps, 0, steps_per_bar, floor_ms=0)
                value = grid._parse(start) + relative._parse(value)
            cuts[name] = grid.cut(value)
        first = cuts["start"]["final_time"]
        messages = [
            f"Music grid {name}: frame={cut['frame']}, residual_ms={cut['residual_ms']!r}" for name, cut in cuts.items()
        ]
        length = cuts["duration"]["final_time"] - first if duration is not None else None
        return first, length, cuts["end"]["final_time"] if end is not None else None, messages
    except (TypeError, ValueError, OverflowError, ZeroDivisionError):
        raise MCPVideoError(
            "Invalid musical grid or trim time", error_type="validation_error", code="invalid_parameter"
        ) from None


def _build_trim_prefix(
    input_path: str,
    start_sec: float,
    duration: str | float | None,
    end: str | float | None,
    *,
    needs_clip_seconds: bool,
) -> tuple[list[str], float | None]:
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
    elif needs_clip_seconds:
        from .engine_probe import probe

        clip_seconds = probe(input_path).duration - start_sec
    return prefix, clip_seconds


def _build_trim_encode_args(staged: str, *, stream_copy: bool) -> list[str]:
    if stream_copy:
        return ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy", *_movflags_args(staged), staged]
    return _build_ffmpeg_cmd(
        output_path=staged,
        video_filter=r"pad=iw+mod(iw\,2):ih+mod(ih\,2)",
        extra=["-map", "0:v?", "-map", "0:a?", "-pix_fmt", "yuv420p"],
    )


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
    bpm: float | None = None,
    fps: float = 30.0,
    offset_s: float = 0.0,
    steps_per_bar: int = 64,
) -> EditResult:
    """Trim by duration or absolute end. BPM enables musical positions and residuals.

    Re-encodes regardless of the legacy accurate flag unless stream_copy is set.
    Stream copy can shift boundaries to keyframes. Progress ranges from 0 to 100.
    """
    if not isinstance(stream_copy, bool):
        raise MCPVideoError("stream_copy must be a boolean", error_type="validation_error", code="invalid_parameter")
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "trimmed")
    _validate_output_path(output)

    messages = []
    if bpm is not None:
        start, duration, end, messages = _grid_trim_times(start, duration, end, bpm, fps, offset_s, steps_per_bar)
    start_sec = _validate_trim_times(start, duration, end)
    prefix, clip_seconds = _build_trim_prefix(
        input_path, start_sec, duration, end, needs_clip_seconds=on_progress is not None
    )

    def render(staged: str) -> None:
        encode = _build_trim_encode_args(staged, stream_copy=stream_copy)
        try:
            if on_progress is None:
                _run_ffmpeg(prefix + encode)
            else:
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

    result = _transactional_edit(
        output, "trim", render, build_result=lambda staged: _build_edit_result(staged, "trim", {"elapsed_ms": None})
    )
    if stream_copy:
        messages.append(
            "Stream copy can snap cuts to nearby keyframes; the output may not match the requested boundaries."
        )
    return result.model_copy(update={"warnings": [*result.warnings, *messages]}) if messages else result
