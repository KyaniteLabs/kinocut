"""Chroma key operation for the FFmpeg engine."""

from __future__ import annotations

from .defaults import DEFAULT_AUDIO_BITRATE
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
from .ffmpeg_helpers import (
    _atomic_output,
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

    # Use MOV with prores_ks 4444 (-profile:v 4) when outputting with transparency;
    # non-MOV containers composite the keyed subject over a black matte.
    is_mov = output.lower().endswith(".mov")

    with _timed_operation() as timing, _atomic_output(output) as staged:
        if is_mov:
            vf = f"chromakey=color={safe_color}:similarity={safe_similarity}:blend={safe_blend},format=yuva444p12le"
            cmd = [
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
            _run_video_only(_run_ffmpeg, cmd)
        else:
            graph = (
                r"[0:v]pad=iw+mod(iw\,2):ih+mod(ih\,2),split[bg][fg];"
                "[bg]drawbox=color=black:t=fill[matte];"
                f"[fg]chromakey=color={safe_color}:similarity={safe_similarity}:blend={safe_blend}[keyed];"
                "[matte][keyed]overlay=shortest=1:format=auto,format=yuv420p[out]"
            )
            cmd = [
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
            _run_ffmpeg(cmd)
        result = _build_edit_result(
            staged,
            "chroma_key",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result


# ---------------------------------------------------------------------------
# Subtitle generation
# ---------------------------------------------------------------------------
