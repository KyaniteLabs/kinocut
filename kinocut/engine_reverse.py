"""Reverse playback operation for the FFmpeg engine."""

from __future__ import annotations

from .engine_probe import probe
from .engine_runtime_utils import (
    _build_edit_result,
    _timed_operation,
)
from .paths import (
    _auto_output,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _atomic_output
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .limits import MAX_REVERSE_FRAME_BYTES
from .models import EditResult


def _enforce_reverse_memory_budget(input_info) -> None:
    """Reject inputs whose decoded frame buffer would OOM FFmpeg's in-RAM reverse filter."""
    if not (input_info.width and input_info.height and input_info.duration):
        return
    fps = float(input_info.fps or 30.0)
    estimated_bytes = int(input_info.width * input_info.height * 1.5 * float(input_info.duration) * fps)
    if estimated_bytes > MAX_REVERSE_FRAME_BYTES:
        est_mb = estimated_bytes / (1024 * 1024)
        cap_mb = MAX_REVERSE_FRAME_BYTES / (1024 * 1024)
        raise MCPVideoError(
            f"Video requires ~{est_mb:.0f} MB of uncompressed RAM to reverse (limit {cap_mb:.0f} MB); "
            "trim into shorter segments first.",
            error_type="validation_error",
            code="reverse_memory_limit",
        )


def reverse(
    input_path: str,
    output_path: str | None = None,
) -> EditResult:
    """Reverse video and audio playback.

    Args:
        input_path: Path to the input video.
        output_path: Where to save the output. Auto-generated if omitted.
    """
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "reversed")
    _validate_output_path(output)

    input_info = probe(input_path)
    _enforce_reverse_memory_budget(input_info)

    with _timed_operation() as timing, _atomic_output(output) as staged:
        if input_info.audio_codec:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    video_filter="reverse",
                    audio_filter="areverse",
                )
            )
        else:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    video_filter="reverse",
                    audio_codec=None,
                    extra=["-an"],
                )
            )

        result = _build_edit_result(
            staged,
            "reverse",
            timing,
        )
    result.output_path = output
    result.elapsed_ms = timing["elapsed_ms"]
    return result
