"""Design quality scoring methods."""

from __future__ import annotations

import logging
import os
import subprocess
import tempfile

from ...defaults import DEFAULT_FFMPEG_TIMEOUT

logger = logging.getLogger(__name__)


class ScoringMixin:
    """Mixin providing design quality scoring methods."""

    def _calculate_technical_score(self, video_path: str) -> float:
        """Calculate technical quality score (0-100) with brand awareness.

        Brand-aware scoring:
        - Dark themes (luma < 50) are not penalized as harshly
        - This accounts for intentional dark brand aesthetics

        When luma or contrast analysis fails, uses a neutral 50 score
        for that metric instead of a perfect score.
        """
        mean_luma = self._get_mean_luma(video_path)
        color_stats = self._analyze_colors(video_path)

        if mean_luma is None:
            brightness_score = 50
        else:
            # Check if this is an intentional dark brand theme
            is_dark_brand_theme = self._is_dark_brand_theme(mean_luma, color_stats)

            if is_dark_brand_theme:
                # For dark brand themes, use a gentler scoring curve
                # that doesn't penalize the intentional aesthetic
                if mean_luma < 30:
                    brightness_score = 65  # Very dark but intentional
                elif mean_luma < 50:
                    brightness_score = 75  # Dark but acceptable
                elif mean_luma < 70:
                    brightness_score = 85  # Elevated dark
                else:
                    brightness_score = max(0, 100 - abs(mean_luma - 128) / 2.56)
            else:
                # Standard scoring for non-brand content
                brightness_score = max(0, 100 - abs(mean_luma - 128) / 1.28)

        contrast = self._get_contrast(video_path)
        contrast_score = min(100, contrast * 2) if contrast is not None else 50

        audio_score = self._calculate_audio_score(video_path)

        return (brightness_score + contrast_score + audio_score) / 3

    def _is_dark_brand_theme(self, mean_luma: float | None, color_stats: dict) -> bool:
        """Detect if video uses an intentional dark brand theme.

        Checks for:
        - Dark background (low luma)
        - Brand color presence (Electric Lime, Midnight Violet)
        - Consistent color palette
        """
        if mean_luma is None or mean_luma > 60:
            return False

        rgb_means = color_stats.get("rgb_means", [128, 128, 128])

        # Check for purple/violet tint (Midnight Violet family)
        has_violet_tint = rgb_means[0] > rgb_means[1] and rgb_means[2] > rgb_means[1]

        # Check for high saturation accents (Electric Lime)
        saturation = color_stats.get("saturation")
        has_vibrant_accents = saturation is not None and saturation > 30

        return has_violet_tint or has_vibrant_accents

    def _calculate_design_score(self) -> float:
        """Calculate design quality score with brand awareness.

        Filters out false positives from brand-consistent choices:
        - Dark themes
        - Brand color casts
        - High saturation (Electric Lime)
        """
        if not self.issues:
            return 100

        # Filter out brand-related false positives
        filtered_issues = []
        for issue in self.issues:
            # Skip dark video warnings for brand themes
            if issue.category == "typography" and "dark video" in issue.message.lower() and issue.severity == "warning":
                continue

            # Skip color cast warnings for brand colors
            if issue.category == "color" and "color cast" in issue.message.lower() and issue.severity == "info":
                continue

            # Skip high saturation warnings (Electric Lime is intentionally vibrant)
            if issue.category == "color" and "saturation" in issue.message.lower() and issue.severity == "info":
                continue

            filtered_issues.append(issue)

        errors = len([i for i in filtered_issues if i.severity == "error"])
        warnings = len([i for i in filtered_issues if i.severity == "warning"])
        infos = len([i for i in filtered_issues if i.severity == "info"])

        score = 100
        score -= errors * 20
        score -= warnings * 10
        score -= infos * 2

        return max(0, score)

    def _calculate_hierarchy_score(self, video_path: str) -> float:
        """Calculate visual hierarchy score using text analysis.

        Analyzes:
        - Text size ratios (heading vs body should be 2.0x+)
        - Number of hierarchy levels (3-4 optimal)
        - Visual weight distribution
        """
        # Get text elements from video
        text_elements = self._detect_text_elements(video_path)

        if not text_elements:
            # Fallback to estimated score based on known good practices
            return self._estimate_hierarchy_score(video_path)

        # Calculate size ratios
        sizes = [t.get("size", 24) for t in text_elements]
        if len(sizes) < 2:
            return 70.0

        sizes_sorted = sorted(set(sizes), reverse=True)

        # Score based on size ratios
        ratio_scores = []
        for i in range(len(sizes_sorted) - 1):
            ratio = sizes_sorted[i] / sizes_sorted[i + 1]
            if ratio >= 2.0:
                ratio_scores.append(1.0)
            elif ratio >= 1.5:
                ratio_scores.append(0.8)
            elif ratio >= 1.2:
                ratio_scores.append(0.6)
            else:
                ratio_scores.append(0.4)

        avg_ratio_score = sum(ratio_scores) / len(ratio_scores) if ratio_scores else 0.7

        # Score based on number of levels (3-4 is optimal)
        num_levels = len(sizes_sorted)
        if num_levels <= 2:
            level_score = 0.7  # Too few levels
        elif num_levels <= 4:
            level_score = 1.0  # Optimal
        elif num_levels <= 5:
            level_score = 0.8  # Acceptable
        else:
            level_score = 0.6  # Too many levels

        # Combined score
        hierarchy_score = avg_ratio_score * 0.6 + level_score * 0.4
        return min(100, hierarchy_score * 100)

    def _estimate_hierarchy_score(self, video_path: str) -> float:
        """Estimate hierarchy score based on video characteristics."""
        # Check resolution (higher res = more room for hierarchy)
        probe = self._probe_video(video_path)
        height = probe.get("height", 1080)

        # Base score on resolution tier
        if height >= 1080:
            base_score = 85
        elif height >= 720:
            base_score = 80
        else:
            base_score = 75

        # Adjust based on duration (longer = more complex scenes possible)
        duration = self._get_duration(video_path)
        if duration > 60:
            base_score -= 5  # Longer videos need more consistent hierarchy

        return base_score

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
