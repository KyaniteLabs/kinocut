"""Path and parameter validation for the long-form transcription path.

The long-form path is the ONLY way to transcribe media up to
``MAX_VIDEO_DURATION``; ordinary ``ai_transcribe`` keeps its 3600s ceiling.
"""

from __future__ import annotations

from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import _get_video_duration, _validate_input_path
from ..limits import (
    LONGFORM_TRANSCRIBE_OVERLAP_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
    MAX_LONGFORM_TRANSCRIBE_CHUNKS,
    MAX_VIDEO_DURATION,
    MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS,
)


def _validate_longform_path(video: str) -> str:
    """Validate long-form path. Raises InputFileError on null bytes /
    unreadable input, MCPVideoError ``invalid_input`` for non-positive
    duration, and MCPVideoError ``duration_too_long`` for >MAX_VIDEO_DURATION."""
    if "\x00" in video:
        raise InputFileError(video, "Invalid path: contains null bytes")
    _validate_input_path(video)
    duration = _get_video_duration(video)
    if duration <= 0:
        raise MCPVideoError(
            f"Could not determine positive duration for {video!r}",
            error_type="validation_error",
            code="invalid_input",
        )
    if duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds long-form cap of {MAX_VIDEO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )
    return video


def _validate_chunk_seconds(chunk_seconds: int) -> int:
    """Validate chunk-window size. Codes: ``invalid_parameter``,
    ``chunk_too_large``, ``chunk_too_small`` (in that order)."""
    if not isinstance(chunk_seconds, int) or isinstance(chunk_seconds, bool) or chunk_seconds <= 0:
        raise MCPVideoError(
            f"chunk_seconds must be a positive int, got {chunk_seconds!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if chunk_seconds > MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS:
        raise MCPVideoError(
            f"chunk_seconds ({chunk_seconds}) exceeds cap of {MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS}",
            error_type="validation_error",
            code="chunk_too_large",
        )
    if chunk_seconds < MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS:
        raise MCPVideoError(
            f"chunk_seconds ({chunk_seconds}) below minimum of {MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS}",
            error_type="validation_error",
            code="chunk_too_small",
        )
    return chunk_seconds


def _validate_overlap_seconds(overlap_seconds: int, chunk_seconds: int) -> int:
    """Validate overlap-window size. Codes: ``invalid_parameter``,
    ``invalid_overlap`` (in that order)."""
    if not isinstance(overlap_seconds, int) or isinstance(overlap_seconds, bool) or overlap_seconds < 0:
        raise MCPVideoError(
            f"overlap_seconds must be a non-negative int, got {overlap_seconds!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if overlap_seconds >= chunk_seconds:
        raise MCPVideoError(
            f"overlap_seconds ({overlap_seconds}) must be smaller than chunk_seconds ({chunk_seconds})",
            error_type="validation_error",
            code="invalid_overlap",
        )
    return overlap_seconds


__all__ = [
    "LONGFORM_TRANSCRIBE_OVERLAP_SECONDS",
    "MAX_LONGFORM_TRANSCRIBE_CHUNKS",
    "MAX_LONGFORM_TRANSCRIBE_CHUNK_SECONDS",
    "MAX_VIDEO_DURATION",
    "MIN_LONGFORM_TRANSCRIBE_CHUNK_SECONDS",
    "_validate_chunk_seconds",
    "_validate_longform_path",
    "_validate_overlap_seconds",
]
