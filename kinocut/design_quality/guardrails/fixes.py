"""Design quality auto-fix methods."""

from __future__ import annotations

import logging
import os
import subprocess

from ...defaults import DEFAULT_FFMPEG_TIMEOUT
from ...errors import ProcessingError
from ...ffmpeg_helpers import _escape_ffmpeg_filter_value, _validate_input_path

logger = logging.getLogger(__name__)


class FixesMixin:
    """Mixin providing design quality auto-fix methods."""

    def _auto_fix_brightness(self, video_path: str, target: float = 128) -> str:
        """Auto-fix brightness by applying gamma correction."""
        _validate_input_path(video_path)
        output_path = f"{os.path.splitext(video_path)[0]}_fixed{os.path.splitext(video_path)[1] or '.mp4'}"

        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", "eq=brightness=0.1:gamma=1.1", "-c:a", "copy", output_path]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            raise ProcessingError(" ".join(cmd), e.returncode, stderr or "Auto-fix failed") from e
        return output_path

    def _auto_fix_contrast(self, video_path: str) -> str:
        """Auto-fix contrast."""
        _validate_input_path(video_path)
        output_path = f"{os.path.splitext(video_path)[0]}_fixed{os.path.splitext(video_path)[1] or '.mp4'}"

        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", "eq=contrast=1.1", "-c:a", "copy", output_path]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            raise ProcessingError(" ".join(cmd), e.returncode, stderr or "Auto-fix failed") from e
        return output_path

    def _auto_fix_saturation(self, video_path: str, boost: float = 1.2) -> str:
        """Auto-fix saturation."""
        _validate_input_path(video_path)
        output_path = f"{os.path.splitext(video_path)[0]}_fixed{os.path.splitext(video_path)[1] or '.mp4'}"

        safe_boost = _escape_ffmpeg_filter_value(str(boost))
        cmd = ["ffmpeg", "-y", "-i", video_path, "-vf", f"eq=saturation={safe_boost}", "-c:a", "copy", output_path]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            raise ProcessingError(" ".join(cmd), e.returncode, stderr or "Auto-fix failed") from e
        return output_path

    def _auto_fix_color_cast(self, video_path: str) -> str:
        """Auto-fix color casts."""
        _validate_input_path(video_path)
        output_path = f"{os.path.splitext(video_path)[0]}_fixed{os.path.splitext(video_path)[1] or '.mp4'}"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video_path,
            "-vf",
            "colorbalance=rm=0.1:gm=0.1:bm=0.1",
            "-c:a",
            "copy",
            output_path,
        ]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            raise ProcessingError(" ".join(cmd), e.returncode, stderr or "Auto-fix failed") from e
        return output_path

    def _auto_normalize_audio(self, video_path: str) -> str:
        """Auto-normalize audio to -16 LUFS."""
        _validate_input_path(video_path)
        output_path = f"{os.path.splitext(video_path)[0]}_fixed{os.path.splitext(video_path)[1] or '.mp4'}"

        cmd = ["ffmpeg", "-y", "-i", video_path, "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-c:v", "copy", output_path]

        try:
            subprocess.run(cmd, capture_output=True, check=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.CalledProcessError as e:
            stderr = e.stderr.decode("utf-8", errors="replace") if isinstance(e.stderr, bytes) else e.stderr
            raise ProcessingError(" ".join(cmd), e.returncode, stderr or "Auto-fix failed") from e
        return output_path

    # ============== UTILITY METHODS ==============
