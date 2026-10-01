"""Design quality auto-fixes sharing validated, atomic FFmpeg publication."""

from __future__ import annotations

import os

from ...ffmpeg_helpers import _atomic_output, _escape_ffmpeg_filter_value, _run_ffmpeg, _validate_input_path


def _run_design_fix(video_path: str, filter_args: list[str]) -> str:
    """Render a fix privately; preserve an existing destination on failure."""
    _validate_input_path(video_path)
    stem, suffix = os.path.splitext(video_path)
    output_path = f"{stem}_fixed{suffix or '.mp4'}"
    with _atomic_output(output_path) as staged:
        _run_ffmpeg(["-i", video_path, *filter_args, staged])
    return output_path


class FixesMixin:
    """Mixin providing the canonical design quality auto-fix implementations."""

    def _auto_fix_brightness(self, video_path: str, target: float = 128) -> str:
        """Apply the existing fixed gamma/brightness adjustment."""
        return _run_design_fix(video_path, ["-vf", "eq=brightness=0.1:gamma=1.1", "-c:a", "copy"])

    def _auto_fix_contrast(self, video_path: str) -> str:
        """Apply the existing contrast adjustment."""
        return _run_design_fix(video_path, ["-vf", "eq=contrast=1.1", "-c:a", "copy"])

    def _auto_fix_saturation(self, video_path: str, boost: float = 1.2) -> str:
        """Apply the requested saturation adjustment."""
        safe_boost = _escape_ffmpeg_filter_value(str(boost))
        return _run_design_fix(video_path, ["-vf", f"eq=saturation={safe_boost}", "-c:a", "copy"])

    def _auto_fix_color_cast(self, video_path: str) -> str:
        """Apply the existing color-balance adjustment."""
        return _run_design_fix(video_path, ["-vf", "colorbalance=rm=0.1:gm=0.1:bm=0.1", "-c:a", "copy"])

    def _auto_normalize_audio(self, video_path: str) -> str:
        """Normalize audio to the existing -16 LUFS target."""
        return _run_design_fix(video_path, ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy"])
