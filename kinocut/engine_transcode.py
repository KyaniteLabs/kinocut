"""Transcoding helpers for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg

# ---------------------------------------------------------------------------
# Normalize — convert to H.264/AAC for editing
# ---------------------------------------------------------------------------


def normalize(input_path: str, output_path: str | None = None) -> str:
    """Normalize a video to H.264 video + AAC audio for reliable editing."""
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "normalized")
    _validate_output_path(output)
    _run_ffmpeg(_build_ffmpeg_cmd(input_path, output_path=output))
    return output
