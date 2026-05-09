"""Video probe and metadata extraction methods."""

from __future__ import annotations

import json
import logging
import subprocess

from ...defaults import DEFAULT_FFMPEG_TIMEOUT

logger = logging.getLogger(__name__)


class ProbeMixin:
    """Mixin providing video probe and metadata methods."""

    def _collect_frame_data(self, video_path: str) -> None:
        """Collect frame-by-frame data for analysis.

        Currently a no-op. Future implementation would extract key frames
        and run computer-vision analysis (edge detection, saliency, OCR).
        """
        return None

    def _probe_video(self, video_path: str) -> dict:
        """Get video metadata."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=width,height,r_frame_rate,duration",
            "-of",
            "json",
            video_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
        data = json.loads(result.stdout)

        if data.get("streams"):
            return data["streams"][0]
        return {}

    def _get_fps(self, video_path: str) -> float:
        """Get video frame rate."""
        probe = self._probe_video(video_path)
        fps_str = probe.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return float(num) / float(den)
        return float(fps_str)

    def _get_duration(self, video_path: str) -> float:
        """Get video duration in seconds."""
        probe = self._probe_video(video_path)
        duration = probe.get("duration", 0)
        return float(duration) if duration else 0

    def _get_mean_luma(self, video_path: str) -> float | None:
        """Get mean luminance. Returns None if analysis fails."""
        cmd = ["ffmpeg", "-i", video_path, "-vf", "signalstats,metadata=mode=print", "-f", "null", "-"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg signalstats timed out for %s", video_path)
            return None

        if result.returncode != 0:
            logger.warning("ffmpeg signalstats failed for %s: %s", video_path, result.stderr[:200])
            return None

        for line in result.stderr.split("\n"):
            if "lavfi.signalstats.YAVG" in line:
                try:
                    return float(line.split("=")[-1].strip())
                except Exception as exc:
                    logger.debug("Luma parsing failed: %s", exc)
        logger.warning("No YAVG signalstats found for %s", video_path)
        return None

    def _get_contrast(self, video_path: str) -> float | None:
        """Get contrast (standard deviation of luminance). Returns None if analysis fails."""
        cmd = ["ffmpeg", "-i", video_path, "-vf", "signalstats,metadata=mode=print", "-f", "null", "-"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg signalstats timed out for %s", video_path)
            return None

        if result.returncode != 0:
            logger.warning("ffmpeg signalstats failed for %s: %s", video_path, result.stderr[:200])
            return None

        for line in result.stderr.split("\n"):
            if "lavfi.signalstats.YSTD" in line:
                try:
                    return float(line.split("=")[-1].strip())
                except Exception as exc:
                    logger.debug("Contrast parsing failed: %s", exc)
        logger.warning("No YSTD signalstats found for %s", video_path)
        return None
