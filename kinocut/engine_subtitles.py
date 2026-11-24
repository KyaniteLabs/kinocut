"""Subtitle burn-in operation for the FFmpeg engine."""

from __future__ import annotations

from typing import Any

from .engine_runtime_utils import _build_edit_result, _run_video_only, _timed_operation
from .ffmpeg_helpers import _atomic_output, _build_ffmpeg_cmd, _run_ffmpeg, _validate_input_path, _validate_output_path
from .models import EditResult
from .paths import _auto_output
from .subtitles_common import staged_burn_source, subtitle_burn_workdir as _synthesis_workdir


def subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str | None = None,
    *,
    check_captions: bool = False,
) -> EditResult:
    """Burn SRT/VTT or authored ASS, preserving authored styling unless overridden."""
    result, summary = burn_subtitles(input_path, subtitle_path, output_path, style, check_captions=check_captions)
    if summary is not None and not summary["passed"]:
        counts = ", ".join(f"{kind}={count}" for kind, count in summary.get("findings", {}).items())
        result.warnings.append(f"Subtitle QA: {summary['status']} ({counts or 'no verified cues'}).")
    return result


def burn_subtitles(
    input_path: str,
    subtitle_path: str,
    output_path: str | None = None,
    style: str | None = None,
    *,
    format_hint: str | None = None,
    check_captions: bool = False,
    qa_profile: str | None = None,
) -> tuple[EditResult, dict[str, Any] | None]:
    """Render captions and optionally return advisory evidence before discarding the ASS."""
    input_path = _validate_input_path(input_path)
    output = output_path or _auto_output(input_path, "subtitled")
    _validate_output_path(output)
    with staged_burn_source(
        subtitle_path, input_path, output, style=style, format_hint=format_hint, workdir_for=_synthesis_workdir
    ) as burn:
        with _timed_operation() as timing, _atomic_output(output) as staged:
            args = _build_ffmpeg_cmd(input_path, output_path=staged, video_filter=burn.video_filter, audio_codec="copy")
            _run_video_only(_run_ffmpeg, args)
            result = _build_edit_result(staged, "subtitles", timing)
        result.output_path = output
        result.elapsed_ms = timing["elapsed_ms"]
        summary = burn.advisory(input_path, profile=qa_profile) if check_captions or qa_profile is not None else None
    return result, summary
