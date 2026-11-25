"""Video analysis and detection methods."""

from __future__ import annotations

import contextlib
import json
import logging
from ...errors import ProcessingError
from ...ffmpeg_helpers import _run_command, _validate_input_path
from ..models import DesignIssue

logger = logging.getLogger(__name__)


class AnalysisMixin:
    """Mixin providing video analysis and detection methods."""

    def _analyze_colors(self, video_path: str) -> dict:
        """Reuse canonical code-domain RGB approximation and saturation metrics."""
        from .measurements import _analyze_design_colors

        return _analyze_design_colors(self, video_path)

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
        video_path = _validate_input_path(video_path)
        cache = getattr(self, "_temporal_motion_cache", None)
        key_fn = getattr(self, "_source_identity_key", None)
        key = key_fn(video_path) if callable(key_fn) else None
        if cache is not None and key is not None and key in cache:
            return dict(cache[key])
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
            result = _run_command(cmd)
        except Exception as exc:
            logger.warning("ffmpeg tblend motion failed for %s: %s", video_path, exc)
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
        stats = {
            "static_fraction": static / n,
            "mean": sum(values) / n,
            "median": median,
            "frames": n,
        }
        if cache is not None and key is not None and key_fn(video_path) == key:
            cache[key] = dict(stats)
        return dict(stats)

    def _analyze_composition(self, video_path: str) -> float | None:
        """Analyze composition quality (0-1)."""
        # Not yet implemented - requires computer vision
        return None

    def _analyze_text_hierarchy(self, video_path: str) -> float | None:
        """Analyze text hierarchy (0-1)."""
        # Not yet implemented - requires text detection
        return None

    def _detect_scene_changes(self, video_path: str) -> list[dict]:
        """Detect scene change timestamps (cached per source identity on this guardrail)."""
        video_path = _validate_input_path(video_path)
        cache = getattr(self, "_scene_changes_cache", None)
        key_fn = getattr(self, "_source_identity_key", None)
        key = key_fn(video_path) if callable(key_fn) else None
        if cache is not None and key is not None and key in cache:
            return [dict(scene) for scene in cache[key]]
        cmd = ["ffmpeg", "-i", video_path, "-vf", "select='gt(scene,0.3)',showinfo", "-f", "null", "-"]
        result = _run_command(cmd)

        scenes = []
        for line in result.stderr.split("\n"):
            if "pts_time:" in line:
                try:
                    time = float(line.split("pts_time:")[1].split()[0])
                    scenes.append({"time": time})
                except Exception as exc:
                    logger.debug("Scene timestamp parsing failed: %s", exc)
                    pass
        if cache is not None and key is not None and key_fn(video_path) == key:
            cache[key] = [dict(scene) for scene in scenes]
        return [dict(scene) for scene in scenes]

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
        """Calculate audio quality score, surfacing unavailable audio explicitly."""
        video_path = _validate_input_path(video_path)
        cmd = ["ffmpeg", "-i", video_path, "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"]
        try:
            result = _run_command(cmd)
        except ProcessingError as exc:
            logger.warning("Audio score measurement unavailable for %s: %s", video_path, exc)
            self._record_audio_unavailable()
            return 50

        try:
            loudness_start = result.stderr.find("{")
            loudness_end = result.stderr.rfind("}") + 1
            loudness_data = json.loads(result.stderr[loudness_start:loudness_end])

            input_lufs = float(loudness_data.get("input_i", -70))

            distance = abs(input_lufs - (-16))
            score = max(0, 100 - distance * 5)
            metrics = getattr(self, "metrics", None)
            if isinstance(metrics, dict):
                metrics["audio"] = {"available": True, "input_lufs": input_lufs, "score": score}
            return score
        except Exception as exc:
            logger.debug("Audio score calculation failed: %s", exc)
            self._record_audio_unavailable()
            return 50

    def _record_audio_unavailable(self) -> None:
        metrics = getattr(self, "metrics", None)
        if isinstance(metrics, dict):
            metrics["audio"] = {"available": False, "score": 50}
        issues = getattr(self, "issues", None)
        if isinstance(issues, list) and not any(
            i.category == "audio" and "Audio loudness analysis unavailable" in i.message for i in issues
        ):
            issues.append(
                DesignIssue(
                    category="audio",
                    severity="info",
                    message="Audio loudness analysis unavailable — used neutral fallback score.",
                    fix_available=False,
                )
            )


# ============== PUBLIC API ==============
