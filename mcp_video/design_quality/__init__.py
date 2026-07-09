"""Visual Design Quality System for mcp-video."""

from __future__ import annotations

import os
import shutil
from typing import Any

from ..errors import ProcessingError
from ..ffmpeg_helpers import _validate_input_path as _validate_input_path
from .guardrails import DesignQualityGuardrails as DesignQualityGuardrails
from .models import DesignIssue as DesignIssue, DesignQualityReport as DesignQualityReport


def design_quality_check(
    video: str,
    auto_fix: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    _validate_input_path(video)
    guardrails = DesignQualityGuardrails()
    report = guardrails.analyze(video, auto_fix=auto_fix)

    # Serialize dataclass report to a dict so _result() expands it properly
    return {
        "success": True,
        "overall_score": report.overall_score,
        "technical_score": report.technical_score,
        "design_score": report.design_score,
        "hierarchy_score": report.hierarchy_score,
        "motion_score": report.motion_score,
        "metrics": guardrails.metrics,
        "issues": [
            {
                "category": i.category,
                "severity": i.severity,
                "message": i.message,
                "frame": i.frame,
                "fix_available": i.fix_available,
                "fix_description": i.fix_description,
            }
            for i in report.issues
        ],
        "fixes_applied": report.fixes_applied,
        "recommendations": report.recommendations,
    }


def fix_design_issues(video: str, output: str | None = None) -> str:
    _validate_input_path(video)
    guardrails = DesignQualityGuardrails()
    report = guardrails.analyze(video, auto_fix=True)

    fixed_path = f"{os.path.splitext(video)[0]}_fixed{os.path.splitext(video)[1] or '.mp4'}"

    if output:
        # If fixes were applied, copy the fixed file to the requested output.
        # Otherwise copy the original so the caller always gets a file at `output`.
        src = fixed_path if report.fixes_applied and os.path.exists(fixed_path) else video
        try:
            shutil.copy2(src, output)
        except OSError as e:
            raise ProcessingError(
                f"copy {src} -> {output}",
                1,
                f"Failed to copy fixed video to output path: {e}",
            ) from e
        return output

    if report.fixes_applied and os.path.exists(fixed_path):
        return fixed_path

    # No fixes applied and no output requested — return original path
    return video
