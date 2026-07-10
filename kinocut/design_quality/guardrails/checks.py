"""Design quality check methods."""

from __future__ import annotations

import logging

from ..models import DesignIssue

logger = logging.getLogger(__name__)


class ChecksMixin:
    """Mixin providing design quality check methods."""

    def _check_layout(self, video_path: str):
        """Check layout quality: safe areas, centering, alignment, spacing."""
        probe = self._probe_video(video_path)
        width = probe.get("width", 1920)
        height = probe.get("height", 1080)

        # Check aspect ratio consistency
        aspect = width / height
        standard_aspects = [16 / 9, 9 / 16, 1 / 1, 4 / 3, 21 / 9]
        closest = min(standard_aspects, key=lambda x: abs(x - aspect))

        if abs(aspect - closest) > 0.01:
            self.issues.append(
                DesignIssue(
                    category="layout",
                    severity="warning",
                    message=(
                        f"Non-standard aspect ratio ({aspect:.2f}). Consider {closest:.2f} for better compatibility."
                    ),
                    fix_available=False,
                )
            )

        # Check if resolution is sufficient for text
        if width < 1920 and height < 1080:
            self.issues.append(
                DesignIssue(
                    category="layout",
                    severity="warning",
                    message=f"Low resolution ({width}x{height}). Text may appear blurry on high-DPI displays.",
                    fix_available=False,
                )
            )

    def _check_typography(self, video_path: str):
        """Check typography: readability, contrast, hierarchy, line length.

        Brand-aware: Dark themes are not flagged if they appear intentional.
        """
        mean_luma = self._get_mean_luma(video_path)
        color_stats = self._analyze_colors(video_path)

        if mean_luma is None:
            self.issues.append(
                DesignIssue(
                    category="typography",
                    severity="info",
                    message="Brightness analysis unavailable — skipped readability check.",
                    fix_available=False,
                )
            )
            return

        # Check if this is an intentional dark brand theme
        is_dark_brand = self._is_dark_brand_theme(mean_luma, color_stats)

        # Check if text would be readable
        if mean_luma < 30 and not is_dark_brand:
            # Only flag dark videos if they don't appear to be intentional brand themes
            self.issues.append(
                DesignIssue(
                    category="typography",
                    severity="warning",
                    message=(
                        "Very dark video may affect text readability. Consider brighter backgrounds for text overlays."
                    ),
                    fix_available=True,
                    auto_fix=lambda v: self._auto_fix_brightness(v, target=40),
                    fix_description="Increase brightness slightly for better text readability",
                )
            )
        elif mean_luma < 30 and is_dark_brand:
            # Dark brand theme detected - info only
            self.issues.append(
                DesignIssue(
                    category="typography",
                    severity="info",
                    message="Dark theme detected. Ensure text has sufficient contrast with background.",
                    fix_available=False,
                )
            )
        elif mean_luma > 220:
            self.issues.append(
                DesignIssue(
                    category="typography",
                    severity="warning",
                    message="Very bright video may wash out light-colored text. Consider darker text or backgrounds.",
                    fix_available=False,
                )
            )

    def _check_color(self, video_path: str):
        """Check color: brand consistency, accessibility, harmony.

        Brand-aware: Brand colors (Electric Lime, Midnight Violet) are not flagged.
        """
        color_stats = self._analyze_colors(video_path)
        mean_luma = self._get_mean_luma(video_path)

        # Check if this is a brand theme
        is_brand_theme = self._is_dark_brand_theme(mean_luma, color_stats)

        # Check for color casts (only flag non-brand colors)
        rgb_means = color_stats.get("rgb_means", [128, 128, 128])
        max_deviation = max(abs(c - 128) for c in rgb_means)

        if max_deviation > 80 and not is_brand_theme:
            dominant = ["R", "G", "B"][rgb_means.index(max(rgb_means))]
            self.issues.append(
                DesignIssue(
                    category="color",
                    severity="info",
                    message=f"Strong {dominant} color cast detected. This may be intentional stylistic choice.",
                    fix_available=False,
                )
            )

        # Check saturation
        saturation = color_stats.get("saturation")
        if saturation is None:
            self.issues.append(
                DesignIssue(
                    category="color",
                    severity="info",
                    message="Saturation analysis unavailable; no saturation classification was made.",
                    fix_available=False,
                )
            )
        elif saturation < 10:
            self.issues.append(
                DesignIssue(
                    category="color",
                    severity="warning",
                    message=f"Very low saturation ({saturation:.1f}%). Video appears desaturated.",
                    fix_available=True,
                    auto_fix=lambda v: self._auto_fix_saturation(v, boost=1.2),
                    fix_description="Increase color saturation",
                )
            )
        elif saturation > 90 and not is_brand_theme:
            # Only flag high saturation if not a brand theme (Electric Lime is intentionally vibrant)
            self.issues.append(
                DesignIssue(
                    category="color",
                    severity="info",
                    message=f"High saturation ({saturation:.1f}%). Ensure this is intentional.",
                    fix_available=False,
                )
            )

    def _check_motion(self, video_path: str):
        """Check motion: animation smoothness, timing, judder."""
        fps = self._get_fps(video_path)

        if fps < self.MIN_ANIMATION_FPS:
            self.issues.append(
                DesignIssue(
                    category="motion",
                    severity="error",
                    message=(
                        f"Low frame rate ({fps} fps). "
                        f"Animation may appear choppy. "
                        f"Minimum recommended: {self.MIN_ANIMATION_FPS} fps."
                    ),
                    fix_available=False,
                )
            )
        elif fps < self.IDEAL_ANIMATION_FPS:
            self.issues.append(
                DesignIssue(
                    category="motion",
                    severity="warning",
                    message=(
                        f"Frame rate ({fps} fps) below ideal "
                        f"({self.IDEAL_ANIMATION_FPS} fps). "
                        "Consider increasing for smoother motion."
                    ),
                    fix_available=False,
                )
            )

        # Check for motion judder
        judder_score = self._analyze_motion_smoothness(video_path)
        if judder_score < 0.7:
            self.issues.append(
                DesignIssue(
                    category="motion",
                    severity="warning",
                    message="Motion judder detected. Consider using smoother easing or higher frame rate.",
                    fix_available=False,
                )
            )

        # Check for insufficient temporal motion (slideshow / frozen output).
        # A clip can have fine fps and no judder yet still be a static slideshow;
        # fps alone cannot catch that, so measure real inter-frame motion. This
        # is advisory (warning) — a deliberately calm shot is valid output.
        motion = self._measure_temporal_motion(video_path)
        if motion is not None and motion["static_fraction"] >= self.MOTION_STATIC_FRACTION_MAX:
            self.issues.append(
                DesignIssue(
                    category="motion",
                    severity="warning",
                    message=(
                        f"Low temporal motion detected ({motion['static_fraction'] * 100:.0f}% of frames "
                        "are near-static). Verify this isn't an unintended slideshow — image-to-video "
                        "output should actually move."
                    ),
                    fix_available=False,
                )
            )

    def _check_composition(self, video_path: str):
        """Check composition: balance, focal points, visual weight."""
        # Analyze frame composition
        composition_score = self._analyze_composition(video_path)

        if composition_score is not None and composition_score < 0.6:
            self.issues.append(
                DesignIssue(
                    category="composition",
                    severity="warning",
                    message="Composition appears unbalanced. Consider rule of thirds or centering focal points.",
                    fix_available=False,
                )
            )

    def _check_hierarchy(self, video_path: str):
        """Check visual hierarchy: text size progression, dominance, emphasis.

        Uses improved text analysis to detect actual hierarchy issues.
        """
        # Get detailed hierarchy analysis
        text_elements = self._detect_text_elements(video_path)

        if text_elements:
            sizes = sorted(set([t.get("size", 24) for t in text_elements]), reverse=True)

            # Check size ratios
            if len(sizes) >= 2:
                ratio = sizes[0] / sizes[1]
                if ratio < 1.5:
                    self.issues.append(
                        DesignIssue(
                            category="hierarchy",
                            severity="warning",
                            message=(
                                f"Text size ratio ({ratio:.1f}x) is too small. "
                                "Use at least 1.5x between heading and body."
                            ),
                            fix_available=False,
                        )
                    )
                elif ratio < 2.0:
                    self.issues.append(
                        DesignIssue(
                            category="hierarchy",
                            severity="info",
                            message=f"Text size ratio ({ratio:.1f}x) could be stronger. Ideal is 2.0x or more.",
                            fix_available=False,
                        )
                    )

            # Check number of levels
            if len(sizes) > 4:
                self.issues.append(
                    DesignIssue(
                        category="hierarchy",
                        severity="info",
                        message=f"Many hierarchy levels ({len(sizes)}). Consider simplifying to 3-4 levels maximum.",
                        fix_available=False,
                    )
                )
        else:
            # Fallback to estimated check
            hierarchy_score = self._analyze_text_hierarchy(video_path)

            if hierarchy_score is not None and hierarchy_score < 0.5:
                self.issues.append(
                    DesignIssue(
                        category="hierarchy",
                        severity="warning",
                        message="Unclear visual hierarchy. Use larger size differences between headings and body text.",
                        fix_available=False,
                    )
                )

    def _check_timing(self, video_path: str):
        """Check timing: pacing, rhythm, animation duration."""
        duration = self._get_duration(video_path)

        # Check if video is too short or too long for content
        if duration < 5:
            self.issues.append(
                DesignIssue(
                    category="timing",
                    severity="info",
                    message=f"Very short duration ({duration:.1f}s). Ensure viewers have time to process content.",
                    fix_available=False,
                )
            )
        elif duration > 180:
            self.issues.append(
                DesignIssue(
                    category="timing",
                    severity="info",
                    message=f"Long duration ({duration:.1f}s). Consider if content could be condensed.",
                    fix_available=False,
                )
            )

        # Check scene pacing
        scene_changes = self._detect_scene_changes(video_path)
        if len(scene_changes) > 0:
            avg_scene_duration = duration / (len(scene_changes) + 1)
            if avg_scene_duration < 2:
                self.issues.append(
                    DesignIssue(
                        category="timing",
                        severity="warning",
                        message=f"Rapid scene changes (avg {avg_scene_duration:.1f}s). May feel rushed.",
                        fix_available=False,
                    )
                )

    def _check_brand(self, video_path: str):
        """Check brand consistency: color palette adherence."""
        # Check if video uses brand colors
        brand_score = self._analyze_brand_colors(video_path)

        if brand_score is not None and brand_score < 0.3:
            self.issues.append(
                DesignIssue(
                    category="color",
                    severity="info",
                    message="Video uses colors outside brand palette. Consider if this is intentional.",
                    fix_available=False,
                )
            )

    def _check_clutter(self, video_path: str):
        """Check for visual clutter: too many elements."""
        clutter_score = self._analyze_visual_clutter(video_path)

        if clutter_score is not None and clutter_score > 0.8:  # High clutter
            self.issues.append(
                DesignIssue(
                    category="composition",
                    severity="warning",
                    message="Visual clutter detected. Consider reducing number of elements per scene.",
                    fix_available=False,
                )
            )

    def _check_caption_duration(self, video_path: str):
        """Check if text/captions are on screen long enough to read."""
        # Estimate if there's enough time to read any text
        self._get_duration(video_path)
        text_events = self._detect_text_events(video_path)

        for event in text_events:
            if event["duration"] < self.MIN_CAPTION_DURATION:
                self.issues.append(
                    DesignIssue(
                        category="timing",
                        severity="error",
                        message=(
                            f"Text appears for only {event['duration']:.1f}s. "
                            f"Minimum recommended: {self.MIN_CAPTION_DURATION}s "
                            "for readability."
                        ),
                        frame=event["frame"],
                        fix_available=False,
                    )
                )

    def _check_transition_timing(self, video_path: str):
        """Check transition durations are appropriate."""
        transitions = self._detect_transitions(video_path)

        for trans in transitions:
            if trans["duration"] < self.MIN_TRANSITION_DURATION:
                self.issues.append(
                    DesignIssue(
                        category="motion",
                        severity="warning",
                        message=(
                            f"Transition too fast ({trans['duration']:.2f}s). "
                            "May be jarring. "
                            f"Minimum: {self.MIN_TRANSITION_DURATION}s."
                        ),
                        frame=trans["frame"],
                        fix_available=False,
                    )
                )
            elif trans["duration"] > self.MAX_TRANSITION_DURATION:
                self.issues.append(
                    DesignIssue(
                        category="motion",
                        severity="info",
                        message=f"Long transition ({trans['duration']:.2f}s). Consider if this slows pacing.",
                        frame=trans["frame"],
                        fix_available=False,
                    )
                )

    def _check_visual_rhythm(self, video_path: str):
        """Check for consistent visual rhythm and pacing."""
        rhythm_score = self._analyze_visual_rhythm(video_path)

        if rhythm_score is not None and rhythm_score < 0.5:
            self.issues.append(
                DesignIssue(
                    category="timing",
                    severity="info",
                    message="Inconsistent visual rhythm. Consider more regular pacing between scenes.",
                    fix_available=False,
                )
            )

    # ============== SCORE CALCULATIONS ==============
