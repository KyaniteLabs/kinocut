"""Video analysis and detection methods."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import subprocess
import tempfile

from ...defaults import DEFAULT_FFMPEG_TIMEOUT
from ...errors import ProcessingError
from ...ffmpeg_helpers import _escape_ffmpeg_filter_value, _validate_input_path

logger = logging.getLogger(__name__)


class AnalysisMixin:
    """Mixin providing video analysis and detection methods."""

    def _detect_text_elements(self, video_path: str) -> list[dict]:
        """Detect text elements in video using frame analysis.

        Returns list of text elements with estimated sizes.
        This is a simplified implementation - full OCR would need Tesseract.
        """
        # Sample frames at different timestamps
        duration = self._get_duration(video_path)
        sample_times = [duration * 0.1, duration * 0.3, duration * 0.5, duration * 0.7, duration * 0.9]

        text_elements = []

        for time_sec in sample_times:
            frame_elements = self._analyze_frame_for_text(video_path, time_sec)
            text_elements.extend(frame_elements)

        return text_elements

    def _analyze_frame_for_text(self, video_path: str, time_sec: float) -> list[dict]:
        """Analyze a single frame for text elements.

        Uses edge detection and region analysis to estimate text presence.
        """

        # Extract frame securely
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp_file:
            frame_path = tmp_file.name
        try:
            cmd = ["ffmpeg", "-y", "-i", video_path, "-ss", str(time_sec), "-vframes", "1", frame_path]
            subprocess.run(cmd, capture_output=True, timeout=30)  # noqa: S603

            if not os.path.exists(frame_path):
                return []

            # Analyze frame for text regions using ffmpeg's signature filter
            # This gives us an estimate of complexity which correlates with text amount
            cmd = ["ffmpeg", "-y", "-i", frame_path, "-vf", "signature=format=xml", "-f", "null", "-"]
            subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603

            # Text detection is not yet implemented (would require OCR).
            # Return empty list rather than fabricated data.
            return []

        except Exception as exc:
            logger.debug("Frame text analysis failed for %s at %ss: %s", video_path, time_sec, exc)
            return []
        finally:
            if os.path.exists(frame_path):
                os.unlink(frame_path)

    def _calculate_motion_score(self, video_path: str) -> float:
        """Calculate motion/animation quality score."""
        fps = self._get_fps(video_path)
        fps_score = min(100, (fps / 30) * 100)

        smoothness = self._analyze_motion_smoothness(video_path)

        return (fps_score + smoothness * 100) / 2

    # ============== AUTO-FIX METHODS ==============

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

    def _analyze_colors(self, video_path: str) -> dict:
        """Analyze color distribution."""
        cached = self._color_analysis_cache.get(video_path)
        if cached is not None:
            return cached

        from ...quality_guardrails import VisualQualityGuardrails

        # Get mean RGB values
        cmd = ["ffmpeg", "-i", video_path, "-vf", "signalstats,metadata=mode=print", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603

        rgb_means = [128, 128, 128]
        for line in result.stderr.split("\n"):
            if "lavfi.signalstats.UAVG" in line:
                with contextlib.suppress(BaseException):
                    rgb_means[1] = float(line.split("=")[-1].strip()) + 128
            elif "lavfi.signalstats.VAVG" in line:
                try:
                    val = float(line.split("=")[-1].strip()) + 128
                    rgb_means[0] = val  # Simplified conversion
                    rgb_means[2] = 255 - val
                except Exception as exc:
                    logger.debug("Color parsing failed: %s", exc)
                    pass

        saturation_report = VisualQualityGuardrails().check_saturation(video_path)
        saturation_metric = saturation_report.details["metric"]
        self.metrics["saturation"] = saturation_metric
        saturation = saturation_metric["value"] if saturation_metric["available"] else None

        result = {
            "rgb_means": rgb_means,
            "saturation": saturation,
            "saturation_metric": saturation_metric,
        }
        self._color_analysis_cache[video_path] = result
        return result

    def _analyze_motion_smoothness(self, video_path: str) -> float:
        """Analyze motion smoothness (0-1)."""
        # Simplified - would need frame difference analysis
        fps = self._get_fps(video_path)
        if fps >= 30:
            return 1.0
        elif fps >= 24:
            return 0.85
        else:
            return 0.6

    def _measure_temporal_motion(self, video_path: str) -> dict | None:
        """Measure inter-frame temporal motion across the clip.

        Uses FFmpeg's ``tblend=all_mode=difference`` to compute the absolute
        difference between consecutive frames, then reads ``signalstats`` YAVG
        (mean luma, 0-255) of each difference frame. Near-zero YAVG means the
        frames are almost identical (no motion). FFmpeg-only — no extra deps.

        Returns a dict with ``static_fraction``/``mean``/``median``/``frames``,
        or ``None`` if analysis fails (caller must treat None as "unknown" and
        not fabricate a passing result).
        """
        floor = getattr(self, "MOTION_STATIC_FRAME_FLOOR", 0.35)
        cmd = [
            "ffmpeg",
            "-i",
            video_path,
            "-vf",
            "tblend=all_mode=difference,signalstats,metadata=mode=print",
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg tblend motion timed out for %s", video_path)
            return None
        except Exception as exc:
            logger.warning("ffmpeg tblend motion failed for %s: %s", video_path, exc)
            return None

        if result.returncode != 0:
            logger.warning("ffmpeg tblend motion failed for %s: %s", video_path, result.stderr[:200])
            return None

        values: list[float] = []
        for line in result.stderr.split("\n"):
            if "lavfi.signalstats.YAVG" in line:
                with contextlib.suppress(ValueError, IndexError):
                    values.append(float(line.split("=")[-1].strip()))

        if not values:
            logger.warning("No tblend YAVG difference frames found for %s", video_path)
            return None

        values.sort()
        n = len(values)
        median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
        static = sum(1 for v in values if v < floor)
        return {
            "static_fraction": static / n,
            "mean": sum(values) / n,
            "median": median,
            "frames": n,
        }

    def _analyze_composition(self, video_path: str) -> float | None:
        """Analyze composition quality (0-1)."""
        # Not yet implemented - requires computer vision
        return None

    def _analyze_text_hierarchy(self, video_path: str) -> float | None:
        """Analyze text hierarchy (0-1)."""
        # Not yet implemented - requires text detection
        return None

    def _detect_scene_changes(self, video_path: str) -> list[dict]:
        """Detect scene change timestamps."""
        cmd = ["ffmpeg", "-i", video_path, "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603

        scenes = []
        for line in result.stderr.split("\n"):
            if "pts_time:" in line:
                try:
                    time = float(line.split("pts_time:")[1].split()[0])
                    scenes.append({"time": time})
                except Exception as exc:
                    logger.debug("Scene timestamp parsing failed: %s", exc)
                    pass
        return scenes

    def _analyze_brand_colors(self, video_path: str) -> float | None:
        """Analyze brand color usage (0-1)."""
        # Not yet implemented - requires color histogram analysis
        return None

    def _analyze_visual_clutter(self, video_path: str) -> float | None:
        """Analyze visual clutter (0-1, higher = more cluttered)."""
        # Not yet implemented - requires edge detection
        return None

    def _detect_text_events(self, video_path: str) -> list[dict]:
        """Detect text events with durations."""
        # Not yet implemented - requires OCR
        return []

    def _detect_transitions(self, video_path: str) -> list[dict]:
        """Detect transitions with durations."""
        scenes = self._detect_scene_changes(video_path)
        transitions = []

        for _i, scene in enumerate(scenes):
            transitions.append(
                {
                    "frame": int(scene["time"] * 30),
                    "time": scene["time"],
                    "duration": 0.5,  # estimated
                }
            )

        return transitions

    def _analyze_visual_rhythm(self, video_path: str) -> float | None:
        """Analyze visual rhythm consistency (0-1)."""
        # Not yet implemented - requires frame difference analysis
        return None

    def _calculate_audio_score(self, video_path: str) -> float:
        """Calculate audio quality score."""
        cmd = ["ffmpeg", "-i", video_path, "-af", "loudnorm=print_format=json", "-f", "null", "-"]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603

        try:
            loudness_start = result.stderr.find("{")
            loudness_end = result.stderr.rfind("}") + 1
            loudness_data = json.loads(result.stderr[loudness_start:loudness_end])

            input_lufs = float(loudness_data.get("input_i", -70))

            distance = abs(input_lufs - (-16))
            return max(0, 100 - distance * 5)
        except Exception as exc:
            logger.debug("Audio score calculation failed: %s", exc)
            return 50


# ============== PUBLIC API ==============
