"""Design quality auto-fixes sharing validated, atomic FFmpeg publication."""

from __future__ import annotations

import contextlib
import os

from ...ffmpeg_helpers import _atomic_output, _escape_ffmpeg_filter_value, _run_ffmpeg, _validate_input_path


def _default_fixed_path(video_path: str) -> str:
    stem, suffix = os.path.splitext(video_path)
    return f"{stem}_fixed{suffix or '.mp4'}"


def _run_design_fix(video_path: str, filter_args: list[str], *, output_path: str | None = None) -> str:
    """Render a fix privately; preserve an existing destination on failure."""
    _validate_input_path(video_path)
    target_path = output_path or _default_fixed_path(video_path)
    with _atomic_output(target_path) as staged:
        _run_ffmpeg(["-i", video_path, *filter_args, staged])
    return target_path


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

    def _apply_auto_fixes(
        self,
        video_path: str,
        issues: list,
        *,
        output_path: str | None = None,
    ) -> list[str]:
        """Apply every available fix and report exactly what reached the output.

        Filter-backed fixes render together in one FFmpeg pass. Applying them
        one by one would have each re-render the original into the same
        ``_fixed`` path, so only the last fix would survive. Failed fixes are
        recorded separately on ``self._last_fixes_failed`` and never mixed into
        ``fixes_applied``; newly created intermediate/discarded ``_fixed`` files
        are cleaned up if any fix fails.
        """
        fixable = [issue for issue in issues if issue.fix_available and issue.auto_fix]
        chained = [issue for issue in fixable if issue.fix_filter]
        applied: list[str] = []
        failed: list[str] = []
        self._last_fixes_failed = failed

        target_path = output_path or _default_fixed_path(video_path)
        preexisted = os.path.lexists(target_path)
        created_target = False

        if chained:
            filters = list(dict.fromkeys(issue.fix_filter for issue in chained))
            try:
                _run_design_fix(video_path, ["-vf", ",".join(filters), "-c:a", "copy"], output_path=target_path)
                created_target = not preexisted and os.path.lexists(target_path)
                applied += [f"{issue.category}: {issue.message}" for issue in chained]
            except Exception as e:
                failed += [f"FAILED {issue.category}: {e!s}" for issue in chained]
        for issue in fixable:
            if issue.fix_filter:
                continue
            try:
                if issue.auto_fix(video_path):
                    applied.append(f"{issue.category}: {issue.message}")
                else:
                    failed.append(f"FAILED {issue.category}: auto-fix produced no output")
            except Exception as e:
                failed.append(f"FAILED {issue.category}: {e!s}")

        if failed and created_target and os.path.lexists(target_path) and not os.path.islink(target_path):
            with contextlib.suppress(OSError):
                os.unlink(target_path)
        return applied
