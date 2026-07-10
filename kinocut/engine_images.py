"""Image sequence creation operation for the FFmpeg engine."""

from __future__ import annotations

import math
import os
import shutil
import tempfile

from .engine_runtime_utils import _build_edit_result, _movflags_args, _quality_args, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .models import EditResult


def create_from_images(
    images: list[str],
    output_path: str | None = None,
    fps: float = 30.0,
) -> EditResult:
    """Create a video from a sequence of images."""
    if not images:
        raise MCPVideoError(
            "No images provided",
            error_type="validation_error",
            code="empty_images",
        )
    fps_value = _coerce_positive_finite_fps(fps)
    validated_images = [_validate_input_path(img) for img in images]
    fps_arg = _format_fps_for_ffmpeg(fps_value)

    output = output_path or _auto_output(images[0], "from_images")
    _validate_output_path(output)
    with _timed_operation() as timing:
        tmpdir = tempfile.mkdtemp(prefix="mcp_video_imgseq_")
        try:
            normalized = _normalize_images(validated_images, tmpdir)
            concat_file = _write_concat_file(normalized, tmpdir, fps_value)
            _run_ffmpeg(
                [
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    concat_file,
                    "-c:v",
                    "libx264",
                    *_quality_args(),
                    "-r",
                    fps_arg,
                    "-pix_fmt",
                    "yuv420p",
                    *_movflags_args(output),
                    output,
                ]
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    return _build_edit_result(
        output,
        "create_from_images",
        timing,
    )


def _format_fps_for_ffmpeg(fps: float) -> str:
    """Serialize FPS without rounding non-integer values before FFmpeg sees them."""
    fps_value = _coerce_positive_finite_fps(fps)
    if fps_value.is_integer():
        return str(int(fps_value))
    return repr(fps_value)


def _coerce_positive_finite_fps(fps: float) -> float:
    try:
        fps_value = float(fps)
    except (OverflowError, TypeError, ValueError) as exc:
        raise MCPVideoError(
            f"fps must be a positive finite number, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        ) from exc
    if fps_value <= 0 or not math.isfinite(fps_value):
        raise MCPVideoError(
            f"fps must be a positive finite number, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return fps_value


def _normalize_images(images: list[str], tmpdir: str) -> list[str]:
    has_png = any(img.lower().endswith(".png") for img in images)
    img_format = "png" if has_png else "jpg"
    ext = f".{img_format}"

    normalized: list[str] = []
    for i, img in enumerate(images):
        norm_path = os.path.join(tmpdir, f"img_{i:04d}{ext}")
        if img_format == "png":
            _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    img,
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-c:v",
                    "png",
                    norm_path,
                ]
            )
        else:
            _run_ffmpeg(
                [
                    "-y",
                    "-i",
                    img,
                    "-vf",
                    "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                    "-q:v",
                    "2",
                    norm_path,
                ]
            )
        normalized.append(norm_path)
    return normalized


def _write_concat_file(normalized: list[str], tmpdir: str, fps: float) -> str:
    concat_file = os.path.join(tmpdir, "concat.txt")
    img_duration = 1.0 / fps
    with open(concat_file, "w") as f:
        for img in normalized:
            abs_path = os.path.abspath(img).replace("\\", "\\\\").replace("'", "'\\''")
            f.write(f"file '{abs_path}'\n")
            f.write(f"duration {img_duration}\n")
        abs_last = os.path.abspath(normalized[-1]).replace("\\", "\\\\").replace("'", "'\\''")
        f.write(f"file '{abs_last}'\n")
    return concat_file
