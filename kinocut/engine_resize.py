"""Resize operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _atomic_output, _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .models import ASPECT_RATIOS, QUALITY_PRESETS, EditResult, QualityLevel
from .validation import _validate_pixel_integer


def _even_dimension(value: float) -> int:
    """Round to the nearest even integer — yuv420p/libx264 reject odd dimensions."""
    return max(2, round(value / 2) * 2)


def _validate_dimension(value: int | None, name: str) -> None:
    if value is not None:
        _validate_pixel_integer(value, name, minimum=1)


def _resize_dimensions(info, width: int | None, height: int | None, aspect_ratio: str | None) -> tuple[int, int]:
    _validate_dimension(width, "width")
    _validate_dimension(height, "height")
    if aspect_ratio:
        if not isinstance(aspect_ratio, str) or aspect_ratio not in ASPECT_RATIOS:
            raise MCPVideoError(
                f"Unknown aspect ratio: {aspect_ratio}. Available: {', '.join(ASPECT_RATIOS)}",
                error_type="input_error",
                code="invalid_aspect_ratio",
            )
        w, h = ASPECT_RATIOS[aspect_ratio]
    elif width is not None and height is not None:
        w, h = width, height
        if w % 2 or h % 2:
            raise MCPVideoError(
                "Explicit resize width and height must be even for the video encoder",
                error_type="validation_error",
                code="invalid_parameter",
            )
    elif width is not None:
        display_w, display_h = getattr(info, "display_width", info.width), getattr(info, "display_height", info.height)
        w, h = _even_dimension(width), _even_dimension(width * display_h / display_w)
    elif height is not None:
        display_w, display_h = getattr(info, "display_width", info.width), getattr(info, "display_height", info.height)
        w, h = _even_dimension(height * display_w / display_h), _even_dimension(height)
    else:
        raise MCPVideoError("resize requires width+height, aspect_ratio, or single dimension")
    _validate_dimension(w, "resolved width")
    _validate_dimension(h, "resolved height")
    return w, h


def resize(
    input_path: str,
    width: int | None = None,
    height: int | None = None,
    aspect_ratio: str | None = None,
    quality: QualityLevel = "high",
    output_path: str | None = None,
) -> EditResult:
    """Resize a video. Use aspect_ratio for preset sizes (e.g. '9:16')."""
    input_path = _validate_input_path(input_path)

    info = probe(input_path)
    if info.width == 0 or info.height == 0:
        raise MCPVideoError(
            "Cannot resize: video has zero dimensions",
            error_type="processing_error",
            code="invalid_input",
        )

    w, h = _resize_dimensions(info, width, height, aspect_ratio)
    if not isinstance(quality, str) or quality not in QUALITY_PRESETS:
        raise MCPVideoError("Unknown resize quality preset", error_type="validation_error", code="invalid_parameter")
    preset = QUALITY_PRESETS[quality]
    output = output_path or _auto_output(input_path, f"{w}x{h}")
    _validate_output_path(output)

    # Scale to fit within target, then pad to exact dimensions
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"

    with _timed_operation() as timing, _atomic_output(output) as staged:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=staged,
                video_filter=vf,
                crf=preset["crf"],
                preset=preset["preset"],
            )
        )
        result = _build_edit_result(staged, "resize", timing)
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
