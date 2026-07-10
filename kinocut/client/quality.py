"""mcp-video Python client — clean API for programmatic video editing."""

from __future__ import annotations

import os
from typing import Any

from ..defaults import DEFAULT_QUALITY_GATE_SCORE


class ClientQualityMixin:
    """Quality operations mixin."""

    def quality_check(self, video: str, fail_on_warning: bool = False) -> dict:
        """Run visual quality guardrails on a video.

        Args:
            video: Video file path
            fail_on_warning: Treat warnings as failures

        Returns:
            dict with keys:
                - video (str): input path
                - overall_score (float): 0-100 average across all checks
                - all_passed (bool): True if every check passed
                - checks (list[dict]): per-check results with name, passed, score, message, details
                - recommendations (list[str]): improvement suggestions
        """
        from ..quality_guardrails import quality_check

        return quality_check(video, fail_on_warning)

    def assert_quality(self, video: str, min_score: float = DEFAULT_QUALITY_GATE_SCORE) -> dict:
        """Raise if a video fails release-quality guardrails."""
        from ..quality_guardrails import assert_quality

        return assert_quality(video, min_score=min_score)

    def release_checkpoint(
        self,
        input_path: str,
        output_dir: str | None = None,
        min_score: float = DEFAULT_QUALITY_GATE_SCORE,
        frame_count: int = 6,
    ) -> dict:
        """Run a hard quality gate, then create human-review artifacts."""
        quality = self.assert_quality(input_path, min_score=min_score)
        review_dir = output_dir or f"{os.path.splitext(input_path)[0]}_release_review"
        os.makedirs(review_dir, exist_ok=True)
        thumb = self.thumbnail(input_path, output=os.path.join(review_dir, "thumbnail.jpg"))
        board = self.storyboard(input_path, output_dir=os.path.join(review_dir, "storyboard"), frame_count=frame_count)
        return {
            "video": input_path,
            "quality": quality,
            "thumbnail": thumb.output_path,
            "storyboard": board.model_dump() if hasattr(board, "model_dump") else board,
            "review_required": True,
            "instructions": "Open the thumbnail/storyboard and inspect the final video before publishing.",
        }

    def design_quality_check(
        self,
        video: str,
        auto_fix: bool = False,
        strict: bool = False,
    ) -> Any:  # DesignQualityReport
        """Run comprehensive design quality analysis.

        Checks layout, typography, color, motion, and composition.
        Can automatically fix issues where possible.

        Args:
            video: Video file path
            auto_fix: If True, automatically apply fixes to the video file.
                WARNING: This modifies the input video directly (overwrites in place).
                Use fix_design_issues() with a separate output path for non-destructive fixes.
            strict: If True, treat warnings as errors

        Returns:
            DesignQualityReport with fields:
                - overall_score (float): 0-100
                - technical_score (float): brightness, contrast, audio
                - design_score (float): layout, typography, color, motion
                - hierarchy_score (float): text size ratios
                - motion_score (float): fps, smoothness
                - issues (list[DesignIssue]): categorized issues with severity (error/warning/info)
                - fixes_applied (list[str]): descriptions of auto-applied fixes
                - recommendations (list[str]): improvement suggestions
        """
        from ..design_quality import design_quality_check

        return design_quality_check(video, auto_fix=auto_fix, strict=strict)

    def fix_design_issues(
        self,
        video: str,
        output: str | None = None,
    ) -> str:
        """Auto-fix design issues in a video.

        Args:
            video: Input video path
            output: Output path (auto-generated if None)

        Returns:
            Path to fixed video
        """
        from ..design_quality import fix_design_issues

        return fix_design_issues(video, output=output)


# Fix the circular import for resize
