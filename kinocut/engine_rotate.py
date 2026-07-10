"""Rotate and flip operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_runtime_utils import (
    _build_edit_result,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .errors import MCPVideoError
from .models import EditResult


def rotate(
    input_path: str,
    angle: int = 0,
    flip_horizontal: bool = False,
    flip_vertical: bool = False,
    output_path: str | None = None,
) -> EditResult:
    """Rotate and/or flip a video.

    Args:
        angle: Rotation angle (0, 90, 180, 270).
        flip_horizontal: Mirror horizontally.
        flip_vertical: Mirror vertically.
    """
    input_path = _validate_input_path(input_path)

    if angle not in (0, 90, 180, 270):
        raise MCPVideoError("angle must be 0, 90, 180, or 270", code="invalid_angle")
    if angle == 0 and not flip_horizontal and not flip_vertical:
        raise MCPVideoError("No rotation or flip specified", code="no_transform")

    filters: list[str] = []
    if flip_horizontal:
        filters.append("hflip")
    if flip_vertical:
        filters.append("vflip")
    if angle == 90:
        filters.append("transpose=1")
    elif angle == 180:
        filters.append("transpose=1,transpose=1")
    elif angle == 270:
        filters.append("transpose=2")

    vf = ",".join(filters)
    output = output_path or _auto_output(input_path, f"rotated_{angle}")
    _validate_output_path(output)

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                output_path=output,
                video_filter=vf,
            )
        )

    return _build_edit_result(
        output,
        "rotate",
        timing,
    )
