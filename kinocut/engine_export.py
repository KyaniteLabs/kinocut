"""Export operation wrapper for the FFmpeg engine."""

from __future__ import annotations

from collections.abc import Callable

from .ffmpeg_helpers import _validate_input_path
from .models import EditResult, ExportFormat, QualityLevel


def export_video(
    input_path: str,
    output_path: str | None = None,
    quality: QualityLevel = "high",
    format: ExportFormat = "mp4",
    on_progress: Callable[[float], None] | None = None,
    two_pass: bool = False,
    target_bitrate: int | None = None,
) -> EditResult:
    """Export a video for final delivery with quality tuning.

    This is a convenience wrapper around :func:`convert` that defaults to
    high-quality mp4.  Use it when you want to re-encode for publishing
    rather than change the format.
    """
    input_path = _validate_input_path(input_path)
    from .engine_convert import convert

    result = convert(
        input_path,
        format=format,
        quality=quality,
        output_path=output_path,
        on_progress=on_progress,
        two_pass=two_pass,
        target_bitrate=target_bitrate,
    )
    result.operation = "export"
    return result
