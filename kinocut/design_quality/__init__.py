"""Visual design quality system for Kinocut."""

from __future__ import annotations

import contextlib
import os
import shutil
from typing import Any

from ..errors import ProcessingError
from ..ffmpeg_helpers import _atomic_output, _validate_input_path as _validate_input_path
from .guardrails import DesignQualityGuardrails as DesignQualityGuardrails
from .guardrails.fixes import _default_fixed_path
from .models import DesignIssue as DesignIssue, DesignQualityReport as DesignQualityReport
from ..validation_errors import exception_kind


def design_quality_check(
    video: str,
    auto_fix: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    _validate_input_path(video)
    guardrails = DesignQualityGuardrails()
    report = guardrails.analyze(video, auto_fix=auto_fix, strict=strict)

    errors = report.get_errors()
    passed = len(errors) == 0 and not report.fixes_failed
    if report.fixes_failed:
        success = False
        error_msg = f"Auto-fix failed ({len(report.fixes_failed)}): {'; '.join(report.fixes_failed)}"
    elif strict and errors:
        success = False
        error_msg = f"Strict design quality check failed with {len(errors)} error(s)"
    else:
        success = True
        error_msg = None

    # Serialize dataclass report to a dict so _result() expands it properly
    payload: dict[str, Any] = {
        "success": success,
        "passed": passed,
        "strict": strict,
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
        "fixes_failed": report.fixes_failed,
        "recommendations": report.recommendations,
    }
    if error_msg is not None:
        payload["error"] = error_msg
    return payload


def fix_design_issues(video: str, output: str | None = None) -> str:
    _validate_input_path(video)
    guardrails = DesignQualityGuardrails()
    default_fixed = _default_fixed_path(video)
    default_preexisted = os.path.lexists(default_fixed)

    report = guardrails.analyze(video, auto_fix=True, fix_output_path=output)

    try:
        if report.fixes_failed:
            raise ProcessingError(
                "fix_design_issues",
                1,
                "",
                reason=f"Design auto-fix failed: {'; '.join(report.fixes_failed)}",
            )

        if output:
            # Filter-backed fixes render directly into `output`; if a non-filter fix
            # wrote to `default_fixed`, copy it to `output` and clean up `default_fixed`.
            if report.fixes_applied and os.path.exists(output):
                return output
            src = default_fixed if report.fixes_applied and os.path.exists(default_fixed) else video
            try:
                with _atomic_output(output) as staged:
                    shutil.copy2(src, staged)
            except OSError as e:
                raise ProcessingError(
                    f"copy {src} -> {output}",
                    1,
                    "",
                    reason=f"Failed to copy fixed video to output path: {exception_kind(e)}",
                ) from e
            return output

        if report.fixes_applied and os.path.exists(default_fixed):
            return default_fixed

        # No fixes applied and no output requested — return original path
        return video
    finally:
        # Clean up any temporary `<stem>_fixed` created beside the input when
        # caller requested a separate `output` or when auto-fixing failed.
        should_clean_default = (output is not None or bool(report.fixes_failed)) and not default_preexisted
        if should_clean_default and os.path.lexists(default_fixed) and not os.path.islink(default_fixed):
            with contextlib.suppress(OSError):
                os.unlink(default_fixed)
