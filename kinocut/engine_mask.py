"""Mask compositing operation for the FFmpeg engine."""

from __future__ import annotations

import os

from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _movflags_args,
    _quality_args,
    _require_filter,
    _run_video_only,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import (
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult

_STILL_MASK_EXTS = frozenset({".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".pgm", ".ppm"})


def apply_mask(
    input_path: str,
    mask_path: str,
    feather: int = 5,
    output_path: str | None = None,
) -> EditResult:
    """Apply an image mask to a video with edge feathering.

    MOV output retains alpha (ProRes 4444); other containers composite the
    masked video over a black matte.

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
    width = info.display_width or info.width
    height = info.display_height or info.height
    is_mov = output.lower().endswith(".mov")
    is_still = os.path.splitext(mask_path)[1].lower() in _STILL_MASK_EXTS
    filter_complex = _mask_filter(width, height, feather, preserve_alpha=is_mov)

    mask_input_args = ["-loop", "1", "-i", mask_path] if is_still else ["-i", mask_path]

    with _timed_operation() as timing, _atomic_output(output) as staged:
        if is_mov:
            codec_args = ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p12le"]
        else:
            codec_args = ["-c:v", "libx264", *_quality_args(), "-pix_fmt", "yuv420p"]
        cmd = [
            "-i",
            input_path,
            *mask_input_args,
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-map",
            "0:a?",
            *codec_args,
            "-c:a",
            "copy",
            *_movflags_args(staged),
            staged,
        ]
        _run_video_only(_run_ffmpeg, cmd)

        result = _build_edit_result(
            staged,
            "apply_mask",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result


def _mask_filter(width: int, height: int, feather: int, *, preserve_alpha: bool = False) -> str:
    safe_width = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(width, "width")))
    safe_height = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(height, "height")))
    safe_feather = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(feather, "feather")))
    mask_chain = f"[1:v]format=gray,scale={safe_width}:{safe_height}"
    if feather > 0:
        mask_chain += f",boxblur={safe_feather}"
    if preserve_alpha:
        return f"[0:v]sidedata=mode=delete:type=DISPLAYMATRIX[src];{mask_chain}[alpha];[src][alpha]alphamerge=shortest=1[out]"
    even_w = width + (width % 2)
    even_h = height + (height % 2)
    safe_even_w = _escape_ffmpeg_filter_value(str(even_w))
    safe_even_h = _escape_ffmpeg_filter_value(str(even_h))
    mask_chain = f"[1:v]format=gray,scale={safe_even_w}:{safe_even_h}"
    if feather > 0:
        mask_chain += f",boxblur={safe_feather}"
    return (
        f"[0:v]sidedata=mode=delete:type=DISPLAYMATRIX,pad={safe_even_w}:{safe_even_h},split[bg][fg];"
        "[bg]drawbox=color=black:t=fill[matte];"
        f"{mask_chain}[alpha];"
        "[fg][alpha]alphamerge=shortest=1[cutout];"
        "[matte][cutout]overlay=shortest=1:format=auto,format=yuv420p[out]"
    )
