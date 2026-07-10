"""Chroma key operation for the FFmpeg engine."""

from __future__ import annotations

from .defaults import DEFAULT_AUDIO_BITRATE
from .engine_runtime_utils import (
    _build_edit_result,
    _movflags_args,
    _quality_args,
    _require_filter,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .ffmpeg_helpers import (
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
)
from .validation import (
    _validate_chroma_color,
    _validate_normalized_float,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path, _escape_ffmpeg_filter_value
from .models import EditResult


def chroma_key(
    input_path: str,
    color: str = "0x00FF00",
    similarity: float = 0.01,
    blend: float = 0.0,
    output_path: str | None = None,
) -> EditResult:
    """Remove a solid color background (green screen / chroma key).

    Args:
        input_path: Path to the input video.
        color: Color to make transparent (default green: 0x00FF00).
        similarity: How similar colors need to be to be keyed out (default 0.01).
        blend: How much to blend the keyed color (default 0.0).
        output_path: Where to save the output. Auto-generated if omitted.

    Note: Use a .mov output path to preserve the alpha channel (transparent
    background). Non-MOV outputs will encode with libx264 which does not
    support transparency.
    """
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "chromakey")
    _validate_output_path(output)

    _require_filter("chromakey", "Chroma key filter")

    # Validate color is a safe 0xRRGGBB hex value (prevents FFmpeg filter injection)
    _validate_chroma_color(color)

    # Validate similarity and blend are in [0.0, 1.0]
    _validate_normalized_float(similarity, "similarity")
    _validate_normalized_float(blend, "blend")

    safe_color = _escape_ffmpeg_filter_value(color)
    safe_similarity = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(similarity, "similarity")))
    safe_blend = _escape_ffmpeg_filter_value(str(_sanitize_ffmpeg_number(blend, "blend")))

    # Use MOV with prores_ks (supports alpha) when outputting with transparency
    is_mov = output.lower().endswith(".mov")

    if is_mov:
        vf = f"chromakey=color={safe_color}:similarity={safe_similarity}:blend={safe_blend},format=yuva444p16le"
        codec_args = ["-c:v", "prores_ks", "-pix_fmt", "yuva444p12le"]
    else:
        vf = f"chromakey=color={safe_color}:similarity={safe_similarity}:blend={safe_blend}"
        codec_args = ["-c:v", "libx264", *_quality_args(), "-c:a", "aac", "-b:a", DEFAULT_AUDIO_BITRATE]

    with _timed_operation() as timing:
        _run_ffmpeg(["-i", input_path, "-vf", vf, *codec_args, *_movflags_args(output), output])

    return _build_edit_result(
        output,
        "chroma_key",
        timing,
    )


# ---------------------------------------------------------------------------
# Subtitle generation
# ---------------------------------------------------------------------------
