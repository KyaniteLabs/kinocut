"""Resize operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_composite_layers import _positive_int
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .limits import MAX_RESOLUTION
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .models import ASPECT_RATIOS, QUALITY_PRESETS, EditResult, QualityLevel


def _even_dimension(value: float) -> int:
    """Round to the nearest even integer — yuv420p/libx264 reject odd dimensions."""
    return max(2, round(value / 2) * 2)


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

    if aspect_ratio and aspect_ratio in ASPECT_RATIOS:
        w, h = ASPECT_RATIOS[aspect_ratio]
    elif aspect_ratio:
        raise MCPVideoError(
            f"Unknown aspect ratio: {aspect_ratio}. Available: {', '.join(ASPECT_RATIOS.keys())}",
            error_type="input_error",
            code="invalid_aspect_ratio",
        )
    elif width and height:
        # Defense in depth: reject non-int / non-positive / oversize dimensions
        # reaching the scaler directly (the workflow layer also type-checks these).
        _positive_int(width, "width")
        _positive_int(height, "height")
        if width > MAX_RESOLUTION or height > MAX_RESOLUTION:
            raise MCPVideoError(
                f"resize dimensions must not exceed {MAX_RESOLUTION}px (got {width}x{height})",
                error_type="validation_error",
                code="invalid_parameter",
            )
        w, h = width, height
    elif width:
        ratio = info.height / info.width
        w, h = _even_dimension(width), _even_dimension(width * ratio)
    elif height:
        ratio = info.width / info.height
        w, h = _even_dimension(height * ratio), _even_dimension(height)
    else:
        raise MCPVideoError("resize requires width+height, aspect_ratio, or single dimension")

    preset = QUALITY_PRESETS[quality]
    output = output_path or _auto_output(input_path, f"{w}x{h}")
    _validate_output_path(output)

    # Scale to fit within target, then pad to exact dimensions
    vf = f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:black"

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=output,
                video_filter=vf,
                crf=preset["crf"],
                preset=preset["preset"],
            )
        )

    return _build_edit_result(
        output,
        "resize",
        timing,
    )
