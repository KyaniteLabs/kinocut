"""Design quality auto-fixes sharing validated, atomic FFmpeg publication."""

from __future__ import annotations

import os

from ...ffmpeg_helpers import _atomic_output, _escape_ffmpeg_filter_value, _run_ffmpeg, _validate_input_path


def _run_design_fix(video_path: str, filter_args: list[str]) -> str:
    """Render a fix privately; preserve an existing destination on failure."""
    _validate_input_path(video_path)
    stem, suffix = os.path.splitext(video_path)
    output_path = f"{stem}_fixed{suffix or '.mp4'}"
    with _atomic_output(output_path) as staged:
        _run_ffmpeg(["-i", video_path, *filter_args, staged])
    return output_path


BRIGHTNESS_FILTER = "eq=brightness=0.1:gamma=1.1"


def saturation_filter(boost: float = 1.2) -> str:
    """The saturation fix filter with an escaped boost value."""
    return f"eq=saturation={_escape_ffmpeg_filter_value(str(boost))}"


class FixesMixin:
    """Mixin providing the canonical design quality auto-fix implementations."""

    def _auto_fix_brightness(self, video_path: str, target: float = 128) -> str:
        """Apply the existing fixed gamma/brightness adjustment."""
        return _run_design_fix(video_path, ["-vf", BRIGHTNESS_FILTER, "-c:a", "copy"])

    def _auto_fix_saturation(self, video_path: str, boost: float = 1.2) -> str:
        """Apply the requested saturation adjustment."""
        return _run_design_fix(video_path, ["-vf", saturation_filter(boost), "-c:a", "copy"])

    def _apply_auto_fixes(self, video_path: str, issues: list) -> list[str]:
        """Apply every available fix and report exactly what reached the output.

        Filter-backed fixes render together in one FFmpeg pass. Applying them
        one by one would have each re-render the original into the same
        ``_fixed`` path, so only the last fix would survive.
        """
        fixable = [issue for issue in issues if issue.fix_available and issue.auto_fix]
        chained = [issue for issue in fixable if issue.fix_filter]
        applied: list[str] = []
        if chained:
            filters = list(dict.fromkeys(issue.fix_filter for issue in chained))
            try:
                _run_design_fix(video_path, ["-vf", ",".join(filters), "-c:a", "copy"])
                applied += [f"{issue.category}: {issue.message}" for issue in chained]
            except Exception as e:
                applied += [f"FAILED {issue.category}: {e!s}" for issue in chained]
        for issue in fixable:
            if issue.fix_filter:
                continue
            try:
                if issue.auto_fix(video_path):
                    applied.append(f"{issue.category}: {issue.message}")
            except Exception as e:
                applied.append(f"FAILED {issue.category}: {e!s}")
        return applied
