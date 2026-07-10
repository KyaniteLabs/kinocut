"""Advanced masking operations for the FFmpeg engine."""

from __future__ import annotations

import os
import tempfile


from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _movflags_args, _quality_args, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult


def luma_key(
    input_path: str,
    threshold: float = 0.5,
    output_path: str | None = None,
) -> EditResult:
    """Mask out dark or bright regions based on luminance.

    Args:
        input_path: Path to the input video.
        threshold: Luminance threshold (0.0-1.0).  Pixels darker than this
            become transparent.
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "lumakey")
    _validate_output_path(output)

    is_mov = output.lower().endswith(".mov")
    safe_thresh = _escape_ffmpeg_filter_value(str(threshold))

    if is_mov:
        vf = f"lutyuv=y=val*{safe_thresh},format=yuva444p16le"
        codec_args = ["-c:v", "prores_ks", "-pix_fmt", "yuva444p12le"]
    else:
        vf = f"lutyuv=y=val*{safe_thresh}"
        codec_args = ["-c:v", "libx264", *_quality_args(), "-c:a", "aac", "-b:a", "128k"]

    with _timed_operation() as timing:
        _run_ffmpeg(["-i", input_path, "-vf", vf, *codec_args, *_movflags_args(output), output])

    return _build_edit_result(
        output,
        "luma_key",
        timing,
        format="mov" if is_mov else "mp4",
    )


def shape_mask(
    input_path: str,
    shape: str = "circle",
    output_path: str | None = None,
    feather: int = 0,
) -> EditResult:
    """Apply a geometric shape mask to a video.

    Generates a mask image and composites it using alphamerge.

    Args:
        input_path: Path to the input video.
        shape: Shape to use ("circle", "rounded_rect", "oval").
        output_path: Where to save the output. Auto-generated if omitted.
        feather: Feather radius in pixels (0 = sharp edges).
    """
    input_path = _validate_input_path(input_path)
    info = probe(input_path)
    output = output_path or _auto_output(input_path, f"mask_{shape}")
    _validate_output_path(output)

    # Generate mask image
    tmpdir = tempfile.mkdtemp(prefix="mcp_video_mask_")
    mask_path = os.path.join(tmpdir, "mask.png")
    _generate_shape_mask(info.width, info.height, shape, mask_path, feather)

    try:
        with _timed_operation() as timing:
            _run_ffmpeg(
                [
                    "-i",
                    input_path,
                    "-i",
                    mask_path,
                    "-filter_complex",
                    "[0:v][1:v]alphamerge",
                    "-c:v",
                    "prores_ks",
                    "-pix_fmt",
                    "yuva444p12le",
                    *_movflags_args(output),
                    output,
                ]
            )
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    return _build_edit_result(
        output,
        "shape_mask",
        timing,
        format="mov",
    )


def _generate_shape_mask(width: int, height: int, shape: str, output_path: str, feather: int) -> None:
    """Generate a grayscale mask image for the given shape."""
    from PIL import Image, ImageDraw, ImageFilter

    img = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(img)

    if shape == "circle":
        radius = min(width, height) // 2
        center = (width // 2, height // 2)
        draw.ellipse(
            [
                center[0] - radius,
                center[1] - radius,
                center[0] + radius,
                center[1] + radius,
            ],
            fill=255,
        )
    elif shape == "rounded_rect":
        corner = min(width, height) // 8
        draw.rounded_rectangle([0, 0, width, height], radius=corner, fill=255)
    elif shape == "oval":
        draw.ellipse([0, 0, width, height], fill=255)
    else:
        # Default to full frame
        draw.rectangle([0, 0, width, height], fill=255)

    if feather > 0:
        img = img.filter(ImageFilter.GaussianBlur(radius=feather))

    img.save(output_path)
