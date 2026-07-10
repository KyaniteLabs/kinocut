"""Visual design quality guardrails for video output.

Automated quality checks similar to code linting, but for video/visual output.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import Any
import contextlib

from .ffmpeg_helpers import _run_ffprobe_json, _validate_input_path
from .errors import MCPVideoError, ProcessingError
from .defaults import DEFAULT_QUALITY_GATE_SCORE
from .limits import QUALITY_GUARDRAILS_TIMEOUT

logger = logging.getLogger(__name__)


def _diagnostic(stage: str, message: str, **extra: Any) -> dict[str, Any]:
    """Create a structured diagnostic payload for guardrail analysis fallbacks."""
    payload: dict[str, Any] = {"stage": stage, "message": message}
    payload.update(extra)
    return payload


def _metric(
    name: str,
    value: float | None,
    unit: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Build the explicit metric contract shared by both quality surfaces."""
    return {
        "name": name,
        "available": value is not None,
        "value": value,
        "unit": unit,
        **metadata,
    }


def _escape_lavfi_path(path: str) -> str:
    """Escape special characters in a file path for FFmpeg lavfi movie= filter.

    Characters that must be escaped: \\ ' : [ ] , ; =
    """
    for char, escaped in [
        ("\\", "\\\\"),
        ("'", "\\'"),
        (":", "\\:"),
        ("[", "\\["),
        ("]", "\\]"),
        (",", "\\,"),
        (";", "\\;"),
        ("=", "\\="),
    ]:
        path = path.replace(char, escaped)
    return path


@dataclass
class QualityReport:
    """Report from a single quality check."""

    check_name: str
    passed: bool
    score: float  # 0-100
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class VisualQualityGuardrails:
    """Automated visual quality checks for video output."""

    # Quality thresholds
    BRIGHTNESS_MIN = 16  # Avoid crushed blacks
    BRIGHTNESS_MAX = 235  # Avoid blown highlights
    BRIGHTNESS_TARGET_MIN = 40
    BRIGHTNESS_TARGET_MAX = 200

    CONTRAST_MIN = 20  # Avoid flat images
    CONTRAST_MAX = 100  # Avoid excessive contrast

    SATURATION_MIN = 10  # Avoid desaturation
    SATURATION_MAX = 120  # Avoid oversaturation

    AUDIO_LUFS_TARGET = -16  # YouTube standard
    AUDIO_LUFS_MIN = -20
    AUDIO_LUFS_MAX = -12
    AUDIO_TRUE_PEAK_MAX = -1  # dBTP

    # Temporal-motion thresholds (issue #10): detect low-motion "slideshow"
    # output that is technically clean but visually frozen.
    #
    # Metric: per-frame-pair temporal motion = mean luma (YAVG, 0-255) of the
    # absolute inter-frame difference (FFmpeg ``tblend=all_mode=difference``).
    # A frame pair below MOTION_STATIC_FRAME_FLOOR is "near-static". If the
    # fraction of near-static frame pairs reaches MOTION_STATIC_FRACTION_MAX,
    # the clip is flagged as slideshow-like / insufficient temporal motion.
    #
    # Calibration (320x240, 30fps synthetic fixtures): frozen clip -> static
    # fraction 1.00; hard-cut slideshow -> ~0.98 (motion only at the cuts);
    # genuinely moving / calm-but-real drift -> 0.00. The 0.90 cutoff leaves a
    # wide margin on both sides, so a deliberately calm shot is not a false
    # positive while a frozen export is caught.
    MOTION_STATIC_FRAME_FLOOR = 0.35  # YAVG diff units below which a pair is near-static
    MOTION_STATIC_FRACTION_MAX = 0.90  # >= this fraction of near-static pairs => slideshow-like

    def _run_ffprobe(self, video: str, filter_name: str) -> dict[str, Any]:
        """Run ffprobe with signalstats filter and parse results."""
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"movie={_escape_lavfi_path(video)},signalstats",
            "-show_entries",
            f"frame_tags={filter_name}",
            "-of",
            "json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=QUALITY_GUARDRAILS_TIMEOUT)  # noqa: S603
            if result.returncode != 0:
                diagnostic = _diagnostic(
                    "ffprobe_signalstats",
                    "ffprobe returned nonzero exit",
                    stderr_excerpt=result.stderr.strip()[:200],
                    filter_name=filter_name,
                )
                logger.warning(
                    "ffprobe signalstats returned nonzero exit for %s (filter=%s): %s",
                    video,
                    filter_name,
                    result.stderr.strip()[:200],
                )
                return {"_error": diagnostic}
            data = json.loads(result.stdout)
            frames = data.get("frames", [])
            if not frames:
                diagnostic = _diagnostic(
                    "ffprobe_signalstats",
                    "ffprobe returned no frames",
                    filter_name=filter_name,
                )
                logger.warning("ffprobe signalstats returned no frames for %s (filter=%s)", video, filter_name)
                return {"_error": diagnostic}
            # Average across all frames
            values = []
            for frame in frames:
                tags = frame.get("tags", {})
                if filter_name in tags:
                    try:
                        values.append(float(tags[filter_name]))
                    except (ValueError, TypeError):
                        continue
            if not values:
                diagnostic = _diagnostic(
                    "ffprobe_signalstats",
                    "ffprobe returned no usable values",
                    filter_name=filter_name,
                )
                logger.warning("ffprobe signalstats returned no usable values for %s (filter=%s)", video, filter_name)
                return {"_error": diagnostic}
            return {"mean": sum(values) / len(values), "values": values}
        except subprocess.TimeoutExpired:
            diagnostic = _diagnostic("ffprobe_signalstats", "ffprobe timed out", filter_name=filter_name)
            logger.warning("ffprobe signalstats timed out for %s (filter=%s)", video, filter_name)
            return {"_error": diagnostic}
        except json.JSONDecodeError:
            diagnostic = _diagnostic("ffprobe_signalstats", "ffprobe returned invalid JSON", filter_name=filter_name)
            logger.warning("ffprobe signalstats returned invalid JSON for %s (filter=%s)", video, filter_name)
            return {"_error": diagnostic}
        except Exception as exc:
            diagnostic = _diagnostic(
                "ffprobe_signalstats",
                "ffprobe signalstats failed",
                filter_name=filter_name,
                error_type=type(exc).__name__,
            )
            logger.warning(
                "ffprobe signalstats failed for %s (filter=%s): %s: %s", video, filter_name, type(exc).__name__, exc
            )
            return {"_error": diagnostic}

    def _run_ffmpeg_signalstats(self, video: str) -> dict[str, Any]:
        """Run ffmpeg with signalstats filter to get video statistics."""
        cmd = [
            "ffmpeg",
            "-i",
            video,
            "-vf",
            "signalstats",
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=QUALITY_GUARDRAILS_TIMEOUT)  # noqa: S603
            # Parse stderr for signalstats output
            stderr = result.stderr
            stats = {}

            # Extract mean values from the output
            for line in stderr.split("\n"):
                if "YUV AVG:" in line or "YAVG:" in line:
                    parts = line.split()
                    for i, part in enumerate(parts):
                        if "YAVG=" in part or "YUV" in part:
                            try:
                                # Try to find numeric value
                                for p in parts[i:]:
                                    if "=" in p:
                                        key, val = p.split("=", 1)
                                        with contextlib.suppress(ValueError):
                                            stats[key.lower()] = float(val)
                            except (ValueError, IndexError):
                                continue
            return stats
        except subprocess.TimeoutExpired:
            logger.warning("ffmpeg signalstats timed out for %s", video)
            return {}
        except Exception as exc:
            logger.warning("ffmpeg signalstats failed for %s: %s: %s", video, type(exc).__name__, exc)
            return {}

    def _mean_signalstat(self, video: str, tag: str) -> float | None:
        """Return the mean for a signalstats frame tag, if available."""
        stats = self._run_ffprobe(video, f"lavfi.signalstats.{tag}")
        if not stats or "mean" not in stats:
            return None
        return float(stats["mean"])

    def _analyze_loudnorm(self, video: str) -> dict[str, Any]:
        """Analyze audio loudness using loudnorm filter."""
        cmd = [
            "ffmpeg",
            "-i",
            video,
            "-af",
            "loudnorm=print_format=json",
            "-f",
            "null",
            "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=QUALITY_GUARDRAILS_TIMEOUT)  # noqa: S603
            # Parse JSON from the output (it's embedded in stderr)
            stderr = result.stderr

            # Find the JSON portion
            json_start = stderr.find("{")
            json_end = stderr.rfind("}") + 1

            if json_start >= 0 and json_end > json_start:
                json_str = stderr[json_start:json_end]
                return json.loads(json_str)
            diagnostic = _diagnostic("ffmpeg_loudnorm", "ffmpeg loudnorm returned no JSON payload")
            logger.warning("ffmpeg loudnorm returned no JSON payload for %s", video)
            return {"_error": diagnostic}
        except subprocess.TimeoutExpired:
            diagnostic = _diagnostic("ffmpeg_loudnorm", "ffmpeg loudnorm timed out")
            logger.warning("ffmpeg loudnorm timed out for %s", video)
            return {"_error": diagnostic}
        except json.JSONDecodeError:
            diagnostic = _diagnostic("ffmpeg_loudnorm", "ffmpeg loudnorm returned invalid JSON")
            logger.warning("ffmpeg loudnorm returned invalid JSON for %s", video)
            return {"_error": diagnostic}
        except Exception as exc:
            diagnostic = _diagnostic(
                "ffmpeg_loudnorm",
                "ffmpeg loudnorm failed",
                error_type=type(exc).__name__,
            )
            logger.warning("ffmpeg loudnorm failed for %s: %s: %s", video, type(exc).__name__, exc)
            return {"_error": diagnostic}

    def _has_audio_stream(self, video: str) -> bool | None:
        """Return whether ffprobe can see an audio stream, or None if probing fails."""
        try:
            probe = _run_ffprobe_json(video)
        except ProcessingError as exc:
            logger.warning("ffprobe audio stream check failed for %s: %s: %s", video, type(exc).__name__, exc)
            return None
        return any(stream.get("codec_type") == "audio" for stream in probe.get("streams", []))

    def _get_rgb_means(self, video: str) -> dict[str, Any] | None:
        """Get approximate mean RGB values for color balance analysis.

        FFmpeg's signalstats filter exposes YUV means, not RGB means. Convert
        those means into RGB-ish values so the color balance check uses fields
        that are actually emitted by signalstats.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"movie={_escape_lavfi_path(video)},signalstats",
            "-show_entries",
            "frame_tags=lavfi.signalstats.YAVG,lavfi.signalstats.UAVG,lavfi.signalstats.VAVG",
            "-of",
            "json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=QUALITY_GUARDRAILS_TIMEOUT)  # noqa: S603
            if result.returncode != 0:
                diagnostic = _diagnostic(
                    "ffprobe_rgb_means",
                    "ffprobe returned nonzero exit",
                    stderr_excerpt=result.stderr.strip()[:200],
                )
                logger.warning("ffprobe RGB means returned nonzero exit for %s: %s", video, result.stderr.strip()[:200])
                return {"_error": diagnostic}

            data = json.loads(result.stdout)
            frames = data.get("frames", [])
            if not frames:
                diagnostic = _diagnostic("ffprobe_rgb_means", "ffprobe returned no frames")
                logger.warning("ffprobe RGB means returned no frames for %s", video)
                return {"_error": diagnostic}

            y_vals, u_vals, v_vals = [], [], []
            for frame in frames:
                tags = frame.get("tags", {})
                if "lavfi.signalstats.YAVG" in tags:
                    with contextlib.suppress(ValueError, TypeError):
                        y_vals.append(float(tags["lavfi.signalstats.YAVG"]))
                if "lavfi.signalstats.UAVG" in tags:
                    with contextlib.suppress(ValueError, TypeError):
                        u_vals.append(float(tags["lavfi.signalstats.UAVG"]))
                if "lavfi.signalstats.VAVG" in tags:
                    with contextlib.suppress(ValueError, TypeError):
                        v_vals.append(float(tags["lavfi.signalstats.VAVG"]))

            if not (y_vals and u_vals and v_vals):
                diagnostic = _diagnostic("ffprobe_rgb_means", "ffprobe returned incomplete YUV values")
                logger.warning("ffprobe RGB means returned incomplete YUV values for %s", video)
                return {"_error": diagnostic}

            y = sum(y_vals) / len(y_vals)
            u = sum(u_vals) / len(u_vals) - 128
            v = sum(v_vals) / len(v_vals) - 128
            r = max(0.0, min(255.0, y + 1.402 * v))
            g = max(0.0, min(255.0, y - 0.344136 * u - 0.714136 * v))
            b = max(0.0, min(255.0, y + 1.772 * u))
            return {
                "r": r,
                "g": g,
                "b": b,
            }
        except subprocess.TimeoutExpired:
            diagnostic = _diagnostic("ffprobe_rgb_means", "ffprobe timed out")
            logger.warning("ffprobe RGB means timed out for %s", video)
            return {"_error": diagnostic}
        except json.JSONDecodeError:
            diagnostic = _diagnostic("ffprobe_rgb_means", "ffprobe returned invalid JSON")
            logger.warning("ffprobe RGB means returned invalid JSON for %s", video)
            return {"_error": diagnostic}
        except Exception as exc:
            diagnostic = _diagnostic("ffprobe_rgb_means", "ffprobe RGB means failed", error_type=type(exc).__name__)
            logger.warning("ffprobe RGB means failed for %s: %s: %s", video, type(exc).__name__, exc)
            return {"_error": diagnostic}

    def check_brightness(self, video: str) -> QualityReport:
        """Check video brightness is in acceptable range."""
        stats = self._run_ffprobe(video, "lavfi.signalstats.YAVG")

        if not stats or "mean" not in stats:
            # Try alternative method
            stats = self._run_ffmpeg_signalstats(video)
            if not stats or "yavg" not in stats:
                return QualityReport(
                    check_name="brightness",
                    passed=False,
                    score=0.0,
                    message="Could not analyze brightness (no video stream or analysis failed)",
                    details={"diagnostic": stats.get("_error")} if stats else {},
                )
            y_avg = stats["yavg"]
        else:
            y_avg = stats["mean"]

        # Y values range from 0-255 in 8-bit video
        passed = self.BRIGHTNESS_TARGET_MIN <= y_avg <= self.BRIGHTNESS_TARGET_MAX

        # Calculate score (100 = perfect at 128, linear falloff)
        target = 128
        deviation = abs(y_avg - target)
        score = float(max(0, 100 - (deviation / target) * 100))

        if y_avg < self.BRIGHTNESS_MIN:
            message = f"Video has crushed blacks (brightness: {y_avg:.1f}). Consider lifting shadows."
        elif y_avg > self.BRIGHTNESS_MAX:
            message = f"Video has blown highlights (brightness: {y_avg:.1f}). Consider lowering exposure."
        elif y_avg < self.BRIGHTNESS_TARGET_MIN:
            message = f"Video is quite dark (brightness: {y_avg:.1f}). Consider slight brightness increase."
        elif y_avg > self.BRIGHTNESS_TARGET_MAX:
            message = f"Video is quite bright (brightness: {y_avg:.1f}). Consider slight brightness decrease."
        else:
            message = f"Brightness is well-balanced (brightness: {y_avg:.1f})"

        return QualityReport(
            check_name="brightness",
            passed=passed,
            score=score,
            message=message,
            details={"y_avg": y_avg, "target_range": [self.BRIGHTNESS_TARGET_MIN, self.BRIGHTNESS_TARGET_MAX]},
        )

    def check_contrast(self, video: str) -> QualityReport:
        """Check video has adequate contrast."""
        y_high = self._mean_signalstat(video, "YHIGH")
        y_low = self._mean_signalstat(video, "YLOW")
        if y_high is None or y_low is None:
            y_high = self._mean_signalstat(video, "YMAX")
            y_low = self._mean_signalstat(video, "YMIN")
        if y_high is None or y_low is None:
            metric = _metric(
                "ffmpeg.signalstats.YHIGH-YLOW",
                None,
                "percent_of_8bit_luma_range",
            )
            return QualityReport(
                check_name="contrast",
                passed=False,
                score=0.0,
                message="Could not analyze contrast (analysis failed)",
                details={
                    "diagnostic": _diagnostic("ffprobe_signalstats", "missing luminance range values"),
                    "metric": metric,
                },
            )

        y_std = max(0.0, (y_high - y_low) / 2.56)  # Approximate contrast on a 0-100 scale.
        metric = _metric(
            "ffmpeg.signalstats.YHIGH-YLOW",
            y_std,
            "percent_of_8bit_luma_range",
            raw={"y_low": y_low, "y_high": y_high, "unit": "8bit_luma"},
        )

        # Standard deviation indicates contrast (higher = more contrast)
        passed = self.CONTRAST_MIN <= y_std <= self.CONTRAST_MAX

        # Calculate score
        optimal_contrast = 50
        deviation = abs(y_std - optimal_contrast)
        score = float(max(0, 100 - (deviation / optimal_contrast) * 100))

        if y_std < self.CONTRAST_MIN:
            message = (
                f"Video has low contrast (std dev: {y_std:.1f}). Image may appear flat. Consider increasing contrast."
            )
        elif y_std > self.CONTRAST_MAX:
            message = f"Video has very high contrast (std dev: {y_std:.1f}). May lose detail in shadows/highlights."
        else:
            message = f"Contrast is good (std dev: {y_std:.1f})"

        return QualityReport(
            check_name="contrast",
            passed=passed,
            score=score,
            message=message,
            details={
                "y_std": y_std,
                "y_low": y_low,
                "y_high": y_high,
                "target_range": [self.CONTRAST_MIN, self.CONTRAST_MAX],
                "metric": metric,
            },
        )

    def check_saturation(self, video: str) -> QualityReport:
        """Check saturation levels."""
        sat_avg = self._mean_signalstat(video, "SATAVG")
        if sat_avg is None:
            metric = _metric(
                "ffmpeg.signalstats.SATAVG",
                None,
                "percent_of_8bit_yuv_saturation_range",
                raw={"value": None, "unit": "signalstats_chroma_magnitude", "full_scale": 181.0},
            )
            return QualityReport(
                check_name="saturation",
                passed=False,
                score=0.0,
                message="Could not analyze saturation (analysis failed)",
                details={
                    "diagnostic": _diagnostic("ffprobe_signalstats", "missing SATAVG values"),
                    "metric": metric,
                },
            )

        # signalstats SATAVG is a per-pixel saturation average. 181 is a
        # practical full-saturation ceiling for 8-bit YUV in FFmpeg output.
        saturation_pct = (sat_avg / 181) * 100
        metric = _metric(
            "ffmpeg.signalstats.SATAVG",
            saturation_pct,
            "percent_of_8bit_yuv_saturation_range",
            raw={"value": sat_avg, "unit": "signalstats_chroma_magnitude", "full_scale": 181.0},
        )

        passed = self.SATURATION_MIN <= saturation_pct <= self.SATURATION_MAX

        # Calculate score
        optimal_sat = 50
        deviation = abs(saturation_pct - optimal_sat)
        score = float(max(0, 100 - (deviation / optimal_sat) * 100))

        if saturation_pct < self.SATURATION_MIN:
            message = f"Video appears desaturated (estimated: {saturation_pct:.1f}%). Consider increasing saturation."
        elif saturation_pct > self.SATURATION_MAX:
            message = f"Video appears oversaturated (estimated: {saturation_pct:.1f}%). Consider reducing saturation."
        else:
            message = f"Saturation is well-balanced (estimated: {saturation_pct:.1f}%)"

        return QualityReport(
            check_name="saturation",
            passed=passed,
            score=score,
            message=message,
            details={"saturation_pct": saturation_pct, "sat_avg": sat_avg, "metric": metric},
        )

    def check_audio_levels(self, video: str) -> QualityReport:
        """Check audio isn't clipping or too quiet."""
        has_audio = self._has_audio_stream(video)
        if has_audio is False:
            return QualityReport(
                check_name="audio_levels",
                passed=True,
                score=100.0,
                message="No audio stream detected in video",
                details={"has_audio": False},
            )

        loudness_data = self._analyze_loudnorm(video)

        if not loudness_data or loudness_data.get("_error"):
            details: dict[str, Any] = {"has_audio": has_audio}
            if loudness_data and loudness_data.get("_error"):
                details["diagnostic"] = loudness_data["_error"]
            return QualityReport(
                check_name="audio_levels",
                passed=False,
                score=0.0,
                message="Could not analyze audio levels (analysis failed)",
                details=details,
            )

        # Parse loudnorm output
        input_i = float(loudness_data.get("input_i", "-70"))  # Integrated LUFS
        input_tp = float(loudness_data.get("input_tp", "-10"))  # True peak dBTP
        input_lra = float(loudness_data.get("input_lra", "1"))  # Loudness range

        # Check against thresholds
        loudness_ok = self.AUDIO_LUFS_MIN <= input_i <= self.AUDIO_LUFS_MAX
        peak_ok = input_tp <= self.AUDIO_TRUE_PEAK_MAX

        passed = loudness_ok and peak_ok

        # Calculate score
        target_lufs = self.AUDIO_LUFS_TARGET
        deviation = abs(input_i - target_lufs)
        score = float(max(0, 100 - (deviation / 10) * 20))  # 20 points per dB deviation

        if input_tp > self.AUDIO_TRUE_PEAK_MAX:
            score = float(score * 0.5)  # Penalize clipping heavily

        messages = []
        if input_i < self.AUDIO_LUFS_MIN:
            messages.append(f"Audio is too quiet ({input_i:.1f} LUFS). Target: {self.AUDIO_LUFS_TARGET} LUFS")
        elif input_i > self.AUDIO_LUFS_MAX:
            messages.append(f"Audio is too loud ({input_i:.1f} LUFS). Target: {self.AUDIO_LUFS_TARGET} LUFS")
        else:
            messages.append(f"Audio loudness is good ({input_i:.1f} LUFS)")

        if input_tp > self.AUDIO_TRUE_PEAK_MAX:
            messages.append(f"Audio is clipping ({input_tp:.1f} dBTP). Reduce volume to prevent distortion.")

        return QualityReport(
            check_name="audio_levels",
            passed=passed,
            score=score,
            message=" ".join(messages),
            details={
                "lufs": input_i,
                "true_peak": input_tp,
                "loudness_range": input_lra,
                "target_lufs": self.AUDIO_LUFS_TARGET,
            },
        )

    def check_color_balance(self, video: str) -> QualityReport:
        """Check for color casts (RGB balance)."""
        rgb = self._get_rgb_means(video)

        if not rgb or "r" not in rgb:
            return QualityReport(
                check_name="color_balance",
                passed=False,
                score=0.0,
                message="Could not analyze color balance (analysis failed)",
                details={"diagnostic": rgb.get("_error")} if isinstance(rgb, dict) and rgb.get("_error") else {},
            )

        r, g, b = rgb["r"], rgb["g"], rgb["b"]

        # Calculate deviation from neutral gray (all channels should be similar)
        avg = (r + g + b) / 3
        if avg == 0:
            avg = 1  # Prevent division by zero

        r_dev = abs(r - avg) / avg * 100
        g_dev = abs(g - avg) / avg * 100
        b_dev = abs(b - avg) / avg * 100

        max_deviation = max(r_dev, g_dev, b_dev)

        # Threshold for color cast detection (15% deviation)
        threshold = 15.0
        passed = max_deviation < threshold

        # Calculate score
        score = float(max(0, 100 - max_deviation * 3))  # 3 points per % deviation

        # Determine color cast
        cast = []
        if r > avg * 1.1:
            cast.append("red")
        elif r < avg * 0.9:
            cast.append("cyan")

        if g > avg * 1.1:
            cast.append("green")
        elif g < avg * 0.9:
            cast.append("magenta")

        if b > avg * 1.1:
            cast.append("blue")
        elif b < avg * 0.9:
            cast.append("yellow")

        if cast:
            cast_str = "/".join(cast)
            message = (
                f"Color cast detected: {cast_str} (max deviation: {max_deviation:.1f}%). "
                "Consider white balance correction."
            )
        else:
            message = f"Color balance is good (max deviation: {max_deviation:.1f}%)"

        return QualityReport(
            check_name="color_balance",
            passed=passed,
            score=score,
            message=message,
            details={
                "r_mean": r,
                "g_mean": g,
                "b_mean": b,
                "max_deviation": max_deviation,
                "color_cast": cast if cast else None,
            },
        )

    def _measure_temporal_motion(self, video: str) -> dict[str, Any]:
        """Measure inter-frame temporal motion across the clip.

        Uses FFmpeg's ``tblend=all_mode=difference`` to produce the absolute
        difference between consecutive frames, then ``signalstats`` to read the
        mean luma (YAVG) of each difference frame. A near-zero YAVG means the
        two frames were almost identical (no motion).

        Returns a dict with ``mean``, ``median``, ``static_fraction`` and
        ``frames`` keys, or ``{"_error": ...}`` if analysis fails. Uses only
        FFmpeg (no extra dependencies).
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"movie={_escape_lavfi_path(video)},tblend=all_mode=difference,signalstats",
            "-show_entries",
            "frame_tags=lavfi.signalstats.YAVG",
            "-of",
            "json",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=QUALITY_GUARDRAILS_TIMEOUT)  # noqa: S603
            if result.returncode != 0:
                diagnostic = _diagnostic(
                    "ffprobe_tblend_motion",
                    "ffprobe returned nonzero exit",
                    stderr_excerpt=result.stderr.strip()[:200],
                )
                logger.warning(
                    "ffprobe tblend motion returned nonzero exit for %s: %s", video, result.stderr.strip()[:200]
                )
                return {"_error": diagnostic}
            data = json.loads(result.stdout)
            frames = data.get("frames", [])
            values = []
            for frame in frames:
                tags = frame.get("tags", {})
                if "lavfi.signalstats.YAVG" in tags:
                    with contextlib.suppress(ValueError, TypeError):
                        values.append(float(tags["lavfi.signalstats.YAVG"]))
            # tblend emits one fewer diff frame than source frames; a single
            # source frame yields no diff frames and cannot have "motion".
            if not values:
                diagnostic = _diagnostic("ffprobe_tblend_motion", "ffprobe returned no usable difference frames")
                logger.warning("ffprobe tblend motion returned no usable frames for %s", video)
                return {"_error": diagnostic}
            values.sort()
            n = len(values)
            mean = sum(values) / n
            median = values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2
            static = sum(1 for v in values if v < self.MOTION_STATIC_FRAME_FLOOR)
            return {
                "mean": mean,
                "median": median,
                "static_fraction": static / n,
                "frames": n,
            }
        except subprocess.TimeoutExpired:
            diagnostic = _diagnostic("ffprobe_tblend_motion", "ffprobe timed out")
            logger.warning("ffprobe tblend motion timed out for %s", video)
            return {"_error": diagnostic}
        except json.JSONDecodeError:
            diagnostic = _diagnostic("ffprobe_tblend_motion", "ffprobe returned invalid JSON")
            logger.warning("ffprobe tblend motion returned invalid JSON for %s", video)
            return {"_error": diagnostic}
        except Exception as exc:
            diagnostic = _diagnostic(
                "ffprobe_tblend_motion", "ffprobe tblend motion failed", error_type=type(exc).__name__
            )
            logger.warning("ffprobe tblend motion failed for %s: %s: %s", video, type(exc).__name__, exc)
            return {"_error": diagnostic}

    def check_motion(self, video: str) -> QualityReport:
        """Check the clip has enough temporal motion (not a frozen slideshow).

        Image-to-video and social creative are expected to actually move. A clip
        that is technically clean but visually frozen (a slideshow / Ken Burns
        sequence with insufficient motion) is flagged here as an advisory
        recommendation rather than a hard technical failure, matching issue #10.
        """
        stats = self._measure_temporal_motion(video)

        if not stats or stats.get("_error") or "static_fraction" not in stats:
            # Analysis failed: report as not-passed so the diagnostic surfaces,
            # consistent with the other checks' failure semantics.
            return QualityReport(
                check_name="temporal_motion",
                passed=False,
                score=0.0,
                message="Could not analyze temporal motion (analysis failed)",
                details={"diagnostic": stats.get("_error")} if isinstance(stats, dict) else {},
            )

        static_fraction = stats["static_fraction"]
        is_slideshow = static_fraction >= self.MOTION_STATIC_FRACTION_MAX

        # Score scales inversely with how static the clip is: a fully static
        # clip scores 0, a continuously-moving clip scores 100.
        score = float(max(0.0, min(100.0, (1.0 - static_fraction) * 100.0)))

        if is_slideshow:
            message = (
                f"Low temporal motion detected ({static_fraction * 100:.0f}% of frames are near-static). "
                "Verify this isn't an unintended slideshow — image-to-video output should actually move."
            )
        else:
            message = f"Temporal motion is adequate ({static_fraction * 100:.0f}% near-static frames)"

        return QualityReport(
            check_name="temporal_motion",
            passed=not is_slideshow,
            score=score,
            message=message,
            details={
                "static_fraction": static_fraction,
                "mean_motion": stats["mean"],
                "median_motion": stats["median"],
                "frames_analyzed": stats["frames"],
                "static_frame_floor": self.MOTION_STATIC_FRAME_FLOOR,
                "static_fraction_threshold": self.MOTION_STATIC_FRACTION_MAX,
            },
        )

    def run_all_checks(self, video: str) -> list[QualityReport]:
        """Run all quality checks and return reports."""
        checks = [
            self.check_brightness(video),
            self.check_contrast(video),
            self.check_saturation(video),
            self.check_audio_levels(video),
            self.check_color_balance(video),
            self.check_motion(video),
        ]
        return checks

    # Checks that are advisory only: they surface as recommendations but do not
    # flip the binary technical gate (all_passed) or weight the overall score.
    # Temporal motion is advisory because a deliberately calm shot is valid
    # creative output; the goal (issue #10) is to *warn* about unintended
    # slideshows, not to hard-fail an otherwise technically clean video.
    ADVISORY_CHECKS = ("temporal_motion",)

    def generate_report(self, video: str) -> dict[str, Any]:
        """Generate comprehensive quality report."""
        checks = self.run_all_checks(video)

        # The technical gate (overall_score, all_passed) is computed from the
        # non-advisory checks only, so a low-motion finding stays a
        # recommendation instead of silently failing a clean video.
        gating = [c for c in checks if c.check_name not in self.ADVISORY_CHECKS]
        overall_score = sum(c.score for c in gating) / len(gating) if gating else 0.0
        all_passed = all(c.passed for c in gating)

        return {
            "video": video,
            "overall_score": round(overall_score, 1),
            "all_passed": all_passed,
            "checks": [
                {
                    "name": c.check_name,
                    "passed": c.passed,
                    "score": round(c.score, 1),
                    "message": c.message,
                    "details": c.details,
                }
                for c in checks
            ],
            "recommendations": [c.message for c in checks if not c.passed],
        }


def quality_check(video: str, fail_on_warning: bool = False) -> dict[str, Any]:
    """Public API for quality checking a video.

    Args:
        video: Path to video file
        fail_on_warning: If True, treat warnings as failures

    Returns:
        Quality report dictionary
    """
    video = _validate_input_path(video)
    guardrails = VisualQualityGuardrails()
    report = guardrails.generate_report(video)

    if fail_on_warning:
        # The stricter score threshold must never erase a failed check.
        report["all_passed"] = bool(report["all_passed"]) and report["overall_score"] >= 80

    return report


def assert_quality(video: str, min_score: float = DEFAULT_QUALITY_GATE_SCORE) -> dict[str, Any]:
    """Hard quality gate for agent workflows before publishing output."""
    report = quality_check(video, fail_on_warning=False)
    report["all_passed"] = report["overall_score"] >= min_score
    if not report["all_passed"]:
        recommendations = "; ".join(report.get("recommendations", []))
        raise MCPVideoError(
            f"Quality gate failed: score {report['overall_score']:.1f} < {min_score:.1f}. {recommendations}",
            error_type="quality_error",
            code="quality_gate_failed",
            suggested_action={
                "auto_fix": False,
                "description": "Inspect storyboard/thumbnail, fix visual/audio issues, then rerun quality checks.",
            },
        )
    return report
