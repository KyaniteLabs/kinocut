"""Strict finite-number validation shared by audio editing operations."""

import math
import re

from .errors import MCPVideoError, ProcessingError
from .limits import FFMPEG_STDERR_DIAGNOSTIC_BYTES

_LOG_DECORATION = r"(?:[ \t]{0,16}\x1b\[[0-9;]{0,32}m){0,8}[ \t]{0,16}"
_AUDIO_ERROR_PREFIX = re.compile(
    r"(?:\A|(?<=[\r\n]))"
    + _LOG_DECORATION
    + r"(?:\[[^\]\r\n]{0,192}@[^\]\r\n]{0,64}\]"
    + _LOG_DECORATION
    + r")?\[(?:error|fatal|panic)\]"
)


def _run_audio_ffmpeg(args: list[str], *, runner):
    """Reject reported decoder errors even when FFmpeg 6 exits successfully.

    Keep the existing runner and decode passes. Level tags distinguish
    processing failures from warnings and loudnorm's measurement JSON.
    """
    command = list(args)
    for index, argument in enumerate(command[:-1]):
        if argument in {"-v", "-loglevel"}:
            command[index + 1] = "level+" + command[index + 1].removeprefix("level+")
            break
    else:
        command = ["-loglevel", "level+info", *command]
    process = runner(command)
    stderr = getattr(process, "stderr", "")
    if isinstance(stderr, str):
        failure = _AUDIO_ERROR_PREFIX.search(stderr)
        if failure:
            # Bound only the extracted diagnostic; the existing runner captures
            # stderr in memory. Avoid splitting or copying that entire buffer.
            diagnostic = stderr[failure.start() : failure.start() + FFMPEG_STDERR_DIAGNOSTIC_BYTES]
            diagnostic = diagnostic.encode("utf-8", errors="replace")[:FFMPEG_STDERR_DIAGNOSTIC_BYTES].decode(
                "utf-8", errors="ignore"
            )
            raise ProcessingError("FFmpeg reported an audio processing error", process.returncode, diagnostic)
    return process


def _audio_number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter")
    try:
        result = float(value)
    except OverflowError:
        raise MCPVideoError(
            f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter"
        ) from None
    if not math.isfinite(result):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter")
    if not low <= result <= high:
        raise MCPVideoError(
            f"{name} must be {low} to {high}, got {value}", error_type="validation_error", code="invalid_parameter"
        )
    return result
