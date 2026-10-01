"""Crop operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult
from .validation import _validate_pixel_integer
from .ffmpeg_helpers import _sanitize_ffmpeg_number


def _resolve_crop_dimensions(
    info, width: int | None, height: int | None, crop_percent: float | None
) -> tuple[int, int]:
    """Resolve crop dimensions from explicit values or percentage."""
    if crop_percent is not None:
        crop_percent = _sanitize_ffmpeg_number(crop_percent, "crop_percent")
        if not 0 < crop_percent <= 100:
            raise MCPVideoError(
                f"crop_percent must be between 0 and 100, got {crop_percent}",
                error_type="validation_error",
                code="invalid_crop_percent",
            )
        w = max(2, int(info.display_width * crop_percent / 100) // 2 * 2)
        h = max(2, int(info.display_height * crop_percent / 100) // 2 * 2)
        return w, h
    if width is None or height is None:
        raise MCPVideoError(
            "Either width and height or crop_percent must be provided",
            error_type="validation_error",
            code="missing_crop_dimensions",
        )
    return _validate_pixel_integer(width, "width", minimum=1), _validate_pixel_integer(height, "height", minimum=1)


def crop(
    input_path: str,
    width: int | None = None,
    height: int | None = None,
    x: int | None = None,
    y: int | None = None,
    output_path: str | None = None,
    crop_percent: float | None = None,
) -> EditResult:
    """Crop a video to a rectangular region.

    Args:
        width: Width of the crop region in pixels.
        height: Height of the crop region in pixels.
        crop_percent: Alternative to width/height — crop to this percentage
            of the video dimensions, centered. E.g. 50 crops a center 50% region.
    """
    input_path = _validate_input_path(input_path)
    info = probe(input_path)
    width, height = _resolve_crop_dimensions(info, width, height, crop_percent)
    if width % 2 or height % 2:
        raise MCPVideoError(
            "Explicit crop width and height must be even for the video encoder",
            error_type="validation_error",
            code="invalid_crop",
        )
    # FFmpeg rotates the picture upright before the crop filter, so sizes and
    # offsets are in display pixels (a portrait phone video stored 1920x1080
    # with a 90° rotation is cropped as 1080x1920).
    frame_w, frame_h = info.display_width, info.display_height
    if width > frame_w or height > frame_h:
        raise MCPVideoError(
            f"Crop size ({width}x{height}) larger than video ({frame_w}x{frame_h})",
            code="crop_too_large",
        )

    if x is None:
        x = (frame_w - width) // 2
    if y is None:
        y = (frame_h - height) // 2
    x = _validate_pixel_integer(x, "x", maximum=frame_w - width)
    y = _validate_pixel_integer(y, "y", maximum=frame_h - height)

    suffix = f"crop_{width}x{height}"
    output = output_path or _auto_output(input_path, suffix)
    _validate_output_path(output)
    safe_w = _escape_ffmpeg_filter_value(str(width))
    safe_h = _escape_ffmpeg_filter_value(str(height))
    safe_x = _escape_ffmpeg_filter_value(str(x))
    safe_y = _escape_ffmpeg_filter_value(str(y))
    crop_filter = f"crop={safe_w}:{safe_h}:{safe_x}:{safe_y}:exact=1"

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=staged,
                video_filter=crop_filter,
                audio_codec="copy",
            )
        )

        result = _build_edit_result(
            staged,
            "crop",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
