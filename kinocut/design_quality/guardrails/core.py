"""Visual Design Quality System for mcp-video.

Comprehensive design quality checks that go beyond technical metrics
to evaluate visual hierarchy, layout, typography, spacing, and motion design.
Includes auto-fix capabilities.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from ...ffmpeg_helpers import _validate_input_path
from ..models import DesignIssue, DesignQualityReport
from .checks import ChecksMixin
from .scoring import ScoringMixin
from .probe import ProbeMixin
from .analysis import AnalysisMixin
from .fixes import FixesMixin

logger = logging.getLogger(__name__)


class DesignQualityGuardrails(ChecksMixin, ScoringMixin, ProbeMixin, AnalysisMixin, FixesMixin):
    """Visual design quality guardrails with auto-fix capabilities.

    Comprehensive checks:
    - Layout: Safe areas, centering, alignment, spacing, clutter
    - Typography: Readability, contrast, hierarchy, line length, consistency
    - Color: Brand consistency, accessibility (WCAG), harmony, casts
    - Motion: Animation smoothness, timing, easing, judder
    - Composition: Visual balance, rule of thirds, focal points
    - Hierarchy: Text size progression, visual dominance
    - Timing: Caption duration, transition timing, pacing
    - Brand: Color palette adherence, consistent styling
    """

    # Design standards
    SAFE_AREA_MARGIN = 0.08  # 8% margin for text safe area
    MIN_TEXT_CONTRAST = 4.5  # WCAG AA standard
    MAX_LINE_LENGTH = 60  # characters for optimal reading
    MIN_FONT_SIZE = 24  # pixels for readability

    # Animation standards
    MIN_ANIMATION_FPS = 24
    IDEAL_ANIMATION_FPS = 30
    JUDDER_THRESHOLD = 0.5  # variance threshold for smooth motion

    # Temporal-motion standards (issue #10): catch low-motion "slideshow" output
    # that is technically clean but visually frozen. Per-frame-pair motion is the
    # mean luma (0-255) of the absolute inter-frame difference; a pair below the
    # floor is "near-static". If at least MOTION_STATIC_FRACTION_MAX of pairs are
    # near-static, the clip reads as a slideshow / insufficient temporal motion.
    # Calibrated on 30fps fixtures: frozen 1.00, hard-cut slideshow ~0.98,
    # genuinely-moving / calm drift 0.00 — so the 0.90 cutoff has wide margin.
    MOTION_STATIC_FRAME_FLOOR = 0.35
    MOTION_STATIC_FRACTION_MAX = 0.90

    # Hierarchy standards
    MIN_SIZE_RATIO = 1.5  # Minimum size difference for hierarchy levels
    IDEAL_SIZE_RATIO = 2.0  # Ideal size difference

    # Timing standards
    MIN_CAPTION_DURATION = 2.0  # seconds - minimum time to read text
    READING_SPEED_WPS = 2.5  # words per second average reading
    MIN_TRANSITION_DURATION = 0.3  # seconds
    MAX_TRANSITION_DURATION = 1.0  # seconds

    # Composition standards
    CLUTTER_THRESHOLD = 10  # max elements per scene
    MIN_ELEMENT_SPACING = 20  # pixels between elements

    # Brand standards
    BRAND_COLORS: ClassVar[list[str]] = ["#CCFF00", "#5B2E91", "#7C3AED", "#6366F1"]  # Electric Lime x Midnight Violet

    def __init__(self):
        self.issues: list[DesignIssue] = []
        self._frame_data: list[dict] = []
        self.metrics: dict[str, dict] = {}
        self._color_analysis_cache: dict[str, dict] = {}

    def analyze(self, video_path: str, auto_fix: bool = False) -> DesignQualityReport:
        """Run comprehensive design quality analysis.

        Args:
            video_path: Path to video file
            auto_fix: If True, automatically apply fixes where possible

        Returns:
            DesignQualityReport with issues and applied fixes
        """
        _validate_input_path(video_path)
        self.issues = []
        self._frame_data = []
        self.metrics = {}
        self._color_analysis_cache = {}
        fixes_applied = []

        # Collect frame-by-frame data
        self._collect_frame_data(video_path)

        # Run all checks
        self._check_layout(video_path)
        self._check_typography(video_path)
        self._check_color(video_path)
        self._check_motion(video_path)
        self._check_composition(video_path)
        self._check_hierarchy(video_path)
        self._check_timing(video_path)
        self._check_brand(video_path)
        self._check_clutter(video_path)
        self._check_caption_duration(video_path)
        self._check_transition_timing(video_path)
        self._check_visual_rhythm(video_path)

        # Calculate scores
        technical_score = self._calculate_technical_score(video_path)
        design_score = self._calculate_design_score()
        hierarchy_score = self._calculate_hierarchy_score(video_path)
        motion_score = self._calculate_motion_score(video_path)
        overall_score = (technical_score + design_score + hierarchy_score + motion_score) / 4

        # Auto-fix if requested
        if auto_fix:
            for issue in self.issues:
                if issue.fix_available and issue.auto_fix:
                    try:
                        result = issue.auto_fix(video_path)
                        if result:
                            fixes_applied.append(f"{issue.category}: {issue.message}")
                    except Exception as e:
                        fixes_applied.append(f"FAILED {issue.category}: {e!s}")

        # Generate 100/100 recommendations
        report = DesignQualityReport(
            video_path=video_path,
            overall_score=overall_score,
            technical_score=technical_score,
            design_score=design_score,
            hierarchy_score=hierarchy_score,
            motion_score=motion_score,
            issues=self.issues,
            fixes_applied=fixes_applied,
        )
        report.recommendations = report.get_100_recommendations()

        return report

    # ============== CHECK METHODS ==============
