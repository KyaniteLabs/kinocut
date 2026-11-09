"""Focused visual checks composed into :mod:`kinocut.quality_guardrails`."""

from __future__ import annotations

from dataclasses import dataclass, replace

from .errors import MCPVideoError
from .quality_guardrail_types import QualityReport, _diagnostic, _metric

# Camera footage keeps the historical point targets in each check. UI captures
# are scored against these ranges instead: a reading inside the range scores
# 100 at the midpoint and 80 at either edge, so intentional dark or light
# product UI clears the default release gate of 80 without moving audio,
# motion, or failed-analysis results.
_UI_CONTRAST = (0.5, 25.0)
_UI_SATURATION = (0.0, 20.0)


@dataclass(frozen=True)
class ContentProfile:
    """Brightness, contrast, and saturation acceptance ranges for one content kind."""

    name: str
    brightness: tuple[float, float]
    contrast: tuple[float, float]
    saturation: tuple[float, float]

    def range_for(self, check_name: str) -> tuple[float, float] | None:
        if check_name == "brightness":
            return self.brightness
        if check_name == "contrast":
            return self.contrast
        if check_name == "saturation":
            return self.saturation
        return None


QUALITY_CONTENT_PROFILES: dict[str, ContentProfile] = {
    "ui-capture-dark": ContentProfile("ui-capture-dark", (20.0, 80.0), _UI_CONTRAST, _UI_SATURATION),
    "ui-capture-light": ContentProfile("ui-capture-light", (170.0, 245.0), _UI_CONTRAST, _UI_SATURATION),
}

_PROFILE_METRICS = {
    "brightness": "y_avg",
    "contrast": "y_std",
    "saturation": "saturation_pct",
}


def resolve_content_profile(profile: str | None) -> ContentProfile | None:
    """Return the named content profile, or None for the camera-footage defaults."""
    if profile is None:
        return None
    found = QUALITY_CONTENT_PROFILES.get(profile)
    if found is None:
        names = ", ".join(QUALITY_CONTENT_PROFILES)
        raise MCPVideoError(
            f"Unknown quality content profile {profile!r}. Expected one of: {names}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    return found


def score_target_range(value: float, low: float, high: float) -> float:
    """Score 100 at the midpoint and 80 at either edge of an inclusive range."""
    span = high - low
    if span <= 0:
        return 100.0 if value == low else 0.0
    half = span / 2.0
    distance = abs(value - ((low + high) / 2.0))
    if distance <= half:
        return 100.0 - 20.0 * (distance / half)
    return max(0.0, 80.0 - 20.0 * ((distance - half) / half))


def _profile_message(check: str, profile: str, value: float, low: float, high: float) -> str:
    text = f"{value:.1f}"
    if check == "brightness":
        if value < low:
            return f"Video is darker than the {profile} profile allows (brightness: {text})."
        if value > high:
            return f"Video is brighter than the {profile} profile allows (brightness: {text})."
        return f"Brightness matches the {profile} profile (brightness: {text})"
    if check == "contrast":
        if value < low:
            return f"Video has lower contrast than the {profile} profile allows (std dev: {text})."
        if value > high:
            return f"Video has higher contrast than the {profile} profile allows (std dev: {text})."
        return f"Contrast matches the {profile} profile (std dev: {text})"
    if value < low:
        return f"Video is less saturated than the {profile} profile allows (estimated: {text}%)."
    if value > high:
        return f"Video is more saturated than the {profile} profile allows (estimated: {text}%)."
    return f"Saturation matches the {profile} profile (estimated: {text}%)"


def apply_content_profile(engine: object, report: QualityReport) -> QualityReport:
    """Rescore a visual check when a content profile is active.

    Missing measurements stay failed. Audio, motion, and color checks have no
    profile range, so they return unchanged.
    """
    profile = getattr(engine, "content_profile", None)
    metric = _PROFILE_METRICS.get(report.check_name)
    if profile is None or metric is None or metric not in report.details:
        return report
    bounds = profile.range_for(report.check_name)
    if bounds is None:
        return report
    value = float(report.details[metric])
    low, high = bounds
    details = dict(report.details)
    details["target_range"] = [low, high]
    return replace(
        report,
        passed=low <= value <= high,
        score=score_target_range(value, low, high),
        message=_profile_message(report.check_name, profile.name, value, low, high),
        details=details,
    )


class QualityChecksMixin:
    """Brightness, contrast and saturation checks for the visual guardrail engine."""

    def check_brightness(self, video: str) -> QualityReport:
        """Check video brightness is in acceptable range."""
        return apply_content_profile(self, self._camera_brightness(video))

    def _camera_brightness(self, video: str) -> QualityReport:
        cached = self._get_all_signalstats(video)
        y_avg = cached.get("lavfi.signalstats.YAVG")

        if y_avg is None:
            stats = self._run_ffprobe(video, "lavfi.signalstats.YAVG")
            if not stats or "mean" not in stats:
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

        passed = self.BRIGHTNESS_TARGET_MIN <= y_avg <= self.BRIGHTNESS_TARGET_MAX
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
        return apply_content_profile(self, self._camera_contrast(video))

    def _camera_contrast(self, video: str) -> QualityReport:
        y_high = self._mean_signalstat(video, "YHIGH")
        y_low = self._mean_signalstat(video, "YLOW")
        if y_high is None or y_low is None:
            y_high = self._mean_signalstat(video, "YMAX")
            y_low = self._mean_signalstat(video, "YMIN")
        if y_high is None or y_low is None:
            metric = _metric("ffmpeg.signalstats.YHIGH-YLOW", None, "percent_of_8bit_luma_range")
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

        y_std = max(0.0, (y_high - y_low) / 2.56)
        metric = _metric(
            "ffmpeg.signalstats.YHIGH-YLOW",
            y_std,
            "percent_of_8bit_luma_range",
            raw={"y_low": y_low, "y_high": y_high, "unit": "8bit_luma"},
        )
        passed = self.CONTRAST_MIN <= y_std <= self.CONTRAST_MAX
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
        return apply_content_profile(self, self._camera_saturation(video))

    def _camera_saturation(self, video: str) -> QualityReport:
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
