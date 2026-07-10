"""Mask compositing operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult


def apply_mask(
    input_path: str,
    mask_path: str,
    feather: int = 5,
    output_path: str | None = None,
) -> EditResult:
    """Apply an image mask to a video with edge feathering.

    Uses alphamerge filter to composite the mask as an alpha channel.

    Args:
        input_path: Path to the input video.
        mask_path: Path to the mask image (white = visible, black = transparent).
        feather: Feather/blur amount at mask edges in pixels (default 5).
        output_path: Where to save the output.
    """
    input_path = _validate_input_path(input_path)
    mask_path = _validate_input_path(mask_path)
    _require_filter("alphamerge", "Advanced masking")
    output = output_path or _auto_output(input_path, "masked")
    _validate_output_path(output)

    info = probe(input_path)
    filter_complex = _mask_filter(info.width, info.height, feather)

    with _timed_operation() as timing:
        _run_ffmpeg(
            _build_ffmpeg_cmd(
                input_path,
                mask_path,
                output_path=output,
                audio_codec="copy",
                extra=[
                    "-filter_complex",
                    filter_complex,
                    "-map",
                    "[out]",
                    "-map",
                    "0:a?",
                ],
            )
        )

    return _build_edit_result(
        output,
        "apply_mask",
        timing,
    )


def _mask_filter(width: int, height: int, feather: int) -> str:
    safe_width = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(width, "width")))
    safe_height = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(height, "height")))
    safe_feather = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(feather, "feather")))
    if feather > 0:
        return (
            f"[1:v]format=gray,scale={safe_width}:{safe_height},colorchannelmixer=aa=1.0,boxblur={safe_feather}[alpha];"
            f"[0:v][alpha]alphamerge,format=yuv420p[out]"
        )
    return (
        f"[1:v]format=gray,scale={safe_width}:{safe_height},colorchannelmixer=aa=1.0[alpha];"
        f"[0:v][alpha]alphamerge,format=yuv420p[out]"
    )
