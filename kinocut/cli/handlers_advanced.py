"""CLI handlers for quality, info, and advanced analysis commands."""

from __future__ import annotations

from typing import Any

from .common import _with_spinner
from .formatting import (
    _format_auto_chapters,
    _format_design_quality,
    _format_fix_design_issues,
    _format_quality_check,
    _format_thumbnail_text,
    _format_video_info_detailed,
)
from .runner import CommandRunner, _out, engine_cmd


def handle_advanced_commands(args: Any, *, use_json: bool) -> bool:
    """Handle quality, info, and advanced analysis commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _auto_chapters(a, j):
        from ..effects_engine import auto_chapters

        r = _with_spinner("Detecting chapters...", auto_chapters, a.input, threshold=a.threshold)

        def _chapter_dict(c):
            if isinstance(c, (list, tuple)):
                return {"timestamp": c[0], "description": c[1]}
            return {"timestamp": c.get("timestamp", ""), "description": c.get("description", "")}

        _out(r, j, _format_auto_chapters, json_transform=lambda r: {"chapters": [_chapter_dict(c) for c in r]})

    runner.register("video-auto-chapters", _auto_chapters)

    runner.register(
        "video-extract-frame",
        engine_cmd(
            "mcp_video.engine:thumbnail",
            "Extracting frame...",
            "input",
            formatter=_format_thumbnail_text,
            timestamp="timestamp",
            output_path="output",
        ),
    )

    def _info_detailed(a, j):
        from ..effects_engine import video_info_detailed

        r = _with_spinner("Getting detailed info...", video_info_detailed, a.input)
        _out(r, j, _format_video_info_detailed)

    runner.register("video-info-detailed", _info_detailed)

    def _quality_check(a, j):
        from ..quality_guardrails import quality_check

        r = _with_spinner("Running quality check...", quality_check, a.input, fail_on_warning=a.fail_on_warning)
        _out(r, j, _format_quality_check)
        if a.fail_on_warning and not r.get("all_passed", False):
            raise SystemExit(1)

    runner.register("video-quality-check", _quality_check)

    def _design_quality(a, j):
        from ..design_quality import design_quality_check

        r = _with_spinner(
            "Running design quality check...",
            design_quality_check,
            a.input,
            auto_fix=a.auto_fix,
            strict=a.strict,
        )
        _out(r, j, _format_design_quality, json_transform=lambda r: r.model_dump() if hasattr(r, "model_dump") else r)

    runner.register("video-design-quality-check", _design_quality)

    def _fix_design(a, j):
        from ..design_quality import fix_design_issues

        r = _with_spinner("Fixing design issues...", fix_design_issues, a.input, a.output)
        _out(r, j, _format_fix_design_issues, json_transform=lambda r: {"success": True, "output_path": r})

    runner.register("video-fix-design-issues", _fix_design)

    return runner.dispatch()
