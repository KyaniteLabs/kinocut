"""Focused visual checks composed into :mod:`kinocut.quality_guardrails`."""

from __future__ import annotations

from .quality_guardrail_types import QualityReport, _diagnostic, _metric


class QualityChecksMixin:
    """Brightness and contrast checks for the visual guardrail engine."""

    def check_brightness(self, video: str) -> QualityReport:
        """Check video brightness is in acceptable range."""
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
