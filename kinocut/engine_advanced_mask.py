"""Advanced masking operations for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile


from .defaults import DEFAULT_AUDIO_BITRATE
from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _movflags_args,
    _quality_args,
    _require_filter,
    _run_video_only,
    _timed_operation,
)
from .paths import _auto_output
from .ffmpeg_helpers import (
    _atomic_output,
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .models import EditResult
from .validation import _validate_normalized_float


def _luma_key_command(input_path: str, safe_thresh: str, staged: str, *, is_mov: bool) -> list[str]:
    if is_mov:
        vf = f"format=yuva444p,lumakey=threshold=0:tolerance={safe_thresh}:softness=0,format=yuva444p12le"
        return [
            "-i",
            input_path,
            "-vf",
            vf,
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c:v",
            "prores_ks",
            "-profile:v",
            "4",
            "-pix_fmt",
            "yuva444p12le",
            "-c:a",
            "copy",
            *_movflags_args(staged),
            staged,
        ]
    graph = (
        r"[0:v]pad=iw+mod(iw\,2):ih+mod(ih\,2),split[bg][fg];"
        "[bg]drawbox=color=black:t=fill[matte];"
        f"[fg]format=yuva444p,lumakey=threshold=0:tolerance={safe_thresh}:softness=0[keyed];"
        "[matte][keyed]overlay=shortest=1:format=auto,format=yuv420p[out]"
    )
    return [
        "-i",
        input_path,
        "-filter_complex",
        graph,
        "-map",
        "[out]",
        "-map",
        "0:a?",
        "-c:v",
        "libx264",
        *_quality_args(),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        DEFAULT_AUDIO_BITRATE,
        *_movflags_args(staged),
        staged,
    ]


def luma_key(
    input_path: str,
    threshold: float = 0.5,
    output_path: str | None = None,
) -> EditResult:
    """Mask out dark regions based on luminance using FFmpeg ``lumakey``.

    MOV output retains alpha (ProRes 4444); other containers composite the
    keyed video over a black matte.

    Args:
        input_path: Path to the input video.
        threshold: Luminance threshold (0.0-1.0). Pixels darker than this
            become transparent.
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    _validate_normalized_float(threshold, "threshold")
    _require_filter("lumakey", "Luma key")
    output = output_path or _auto_output(input_path, "lumakey")
    _validate_output_path(output)

    is_mov = output.lower().endswith(".mov")
    safe_thresh = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(threshold, "threshold")))

    with _timed_operation() as timing, _atomic_output(output) as staged:
        cmd = _luma_key_command(input_path, safe_thresh, staged, is_mov=is_mov)
        if is_mov:
            _run_video_only(_run_ffmpeg, cmd)
        else:
            _run_ffmpeg(cmd)
        result = _build_edit_result(
            staged,
            "luma_key",
            timing,
            format="mov" if is_mov else (os.path.splitext(output)[1].lower().lstrip(".") or "mp4"),
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result


def shape_mask(
    input_path: str,
    shape: str = "circle",
    output_path: str | None = None,
    feather: int = 0,
) -> EditResult:
    """Apply a geometric shape mask to a video.

    MOV output retains alpha; other containers composite the shape over black.

    Args:
        input_path: Path to the input video.
        shape: Shape to use ("circle", "rounded_rect", "oval").
        output_path: Where to save the output. Auto-generated if omitted.
        feather: Feather radius in pixels (0 = sharp edges).
    """
    input_path = _validate_input_path(input_path)
    info = probe(input_path)
    output = output_path or _auto_output(input_path, f"mask_{shape}", ext=".mov")
    _validate_output_path(output)

    mask_w = info.display_width or info.width
    mask_h = info.display_height or info.height
    # Generate mask image in display coordinates (matches FFmpeg autorotate)
    tmpdir = tempfile.mkdtemp(prefix="mcp_video_mask_")
    mask_path = os.path.join(tmpdir, "mask.png")
    try:
        _generate_shape_mask(mask_w, mask_h, shape, mask_path, feather)
        with _timed_operation() as timing, _atomic_output(output) as staged:
            _run_video_only(_run_ffmpeg, _shape_mask_command(input_path, mask_path, staged))
            result = _build_edit_result(
                staged,
                "shape_mask",
                timing,
                format=os.path.splitext(output)[1].lower().lstrip("."),
            )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result


def _shape_mask_command(input_path: str, mask_path: str, output: str) -> list[str]:
    suffix = os.path.splitext(output)[1].lower()
    if suffix == ".mov":
        graph = "[0:v]sidedata=mode=delete:type=DISPLAYMATRIX[src];[src][1:v]alphamerge=shortest=1[masked]"
        codec = ["-c:v", "prores_ks", "-profile:v", "4", "-pix_fmt", "yuva444p12le"]
    else:
        graph = (
            r"[0:v]sidedata=mode=delete:type=DISPLAYMATRIX,pad=iw+mod(iw\,2):ih+mod(ih\,2),split[background][content];"
            "[background]drawbox=color=black:t=fill[black];"
            r"[1:v]pad=iw+mod(iw\,2):ih+mod(ih\,2)[mask_even];"
            "[content][mask_even]alphamerge=shortest=1[cutout];"
            "[black][cutout]overlay=shortest=1:format=auto,format=yuv420p[masked]"
        )
        codec = ["-c:v", "libvpx-vp9" if suffix == ".webm" else "libx264", "-pix_fmt", "yuv420p"]
    return [
        "-i",
        input_path,
        "-loop",
        "1",
        "-i",
        mask_path,
        "-filter_complex",
        graph,
        "-map",
        "[masked]",
        "-map",
        "0:a?",
        *codec,
        "-c:a",
        "libopus" if suffix == ".webm" else "copy",
        *_movflags_args(output),
        output,
    ]


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
