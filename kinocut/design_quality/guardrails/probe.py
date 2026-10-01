"""Video probe and metadata extraction methods."""

from __future__ import annotations

import json
import logging
from ...errors import ProcessingError
from ...ffmpeg_helpers import _run_command, _validate_input_path

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
        video_path = _validate_input_path(video_path)
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,duration",
            "-of",
            "json",
            video_path,
        ]
        result = _run_command(cmd)
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProcessingError(" ".join(cmd), result.returncode, f"Invalid JSON from ffprobe: {exc}") from None

        if data.get("streams"):
            return data["streams"][0]
        return {}

    def _get_fps(self, video_path: str) -> float:
        """Get video frame rate."""
        probe = self._probe_video(video_path)
        fps_str = probe.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            numerator = float(num)
            denominator = float(den)
            if numerator <= 0 or denominator <= 0:
                return 30.0
            return numerator / denominator
        fps = float(fps_str)
        return fps if fps > 0 else 30.0

    def _get_duration(self, video_path: str) -> float:
        """Get video duration in seconds."""
        probe = self._probe_video(video_path)
        duration = probe.get("duration", 0)
        return float(duration) if duration else 0

    def _get_mean_luma(self, video_path: str) -> float | None:
        """Return clip-average canonical luma, or None if unavailable."""
        from .measurements import _quality_engine

        return _quality_engine(self)._mean_signalstat(video_path, "YAVG")

    def _get_contrast(self, video_path: str) -> float | None:
        """Get the shared YHIGH/YLOW contrast metric used by technical QA."""
        from .measurements import _quality_engine

        report = _quality_engine(self).check_contrast(video_path)
        metric = report.details["metric"]
        self.metrics["contrast"] = metric
        return metric["value"] if metric["available"] else None
