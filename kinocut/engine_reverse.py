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
from .ffmpeg_helpers import (
    _build_ffmpeg_cmd,
    _run_ffmpeg,
)
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .models import EditResult


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

    with _timed_operation() as timing:
        if input_info.audio_codec:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_filter="reverse",
                    audio_filter="areverse",
                )
            )
        else:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
                    video_filter="reverse",
                    audio_codec=None,
                    extra=["-an"],
                )
            )

    return _build_edit_result(
        output,
        "reverse",
        timing,
    )
