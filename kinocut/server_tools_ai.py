"""MCP tool registrations for AI analysis and quality guardrails."""

from __future__ import annotations

import os
from typing import Any

from .defaults import DEFAULT_QUALITY_GATE_SCORE
from .errors import MCPVideoError
from .server_app import _error_result, _result, _safe_tool, _validation_error, mcp
from .ffmpeg_helpers import _validate_input_path
from .validation import (
    VALID_COLOR_GRADE_STYLES,
    VALID_DEMUCS_MODELS,
    VALID_UPSCALE_MODELS,
    VALID_WHISPER_MODELS,
)

# ---------------------------------------------------------------------------
# AI Feature Tools
# ---------------------------------------------------------------------------


@mcp.tool()
@_safe_tool
def video_ai_remove_silence(
    input_path: str,
    output_path: str,
    silence_threshold: float = -50,
    min_silence_duration: float = 0.5,
    keep_margin: float = 0.1,
) -> dict[str, Any]:
    """Remove silent sections from video."""
    if not -70 <= silence_threshold <= 0:
        return _validation_error(f"silence_threshold must be between -70 and 0, got {silence_threshold}")
    if min_silence_duration <= 0:
        return _validation_error(f"min_silence_duration must be positive, got {min_silence_duration}")
    if keep_margin < 0:
        return _validation_error(f"keep_margin must be non-negative, got {keep_margin}")
    input_path = _validate_input_path(input_path)
    from .ai_engine import ai_remove_silence

    return _result(ai_remove_silence(input_path, output_path, silence_threshold, min_silence_duration, keep_margin))


@mcp.tool()
@_safe_tool
def video_ai_transcribe(
    input_path: str,
    output_srt: str | None = None,
    model: str = "base",
    language: str | None = None,
) -> dict[str, Any]:
    """Transcribe speech to text using Whisper."""
    if model not in VALID_WHISPER_MODELS:
        return _validation_error(f"Invalid model: must be one of {sorted(VALID_WHISPER_MODELS)}, got '{model}'")
    input_path = _validate_input_path(input_path)
    from .ai_engine import ai_transcribe

    return _result(ai_transcribe(input_path, output_srt, model, language))


@mcp.tool()
@_safe_tool
def video_analyze(
    input_path: str,
    whisper_model: str = "base",
    language: str | None = None,
    scene_threshold: float = 0.3,
    include_transcript: bool = True,
    include_scenes: bool = True,
    include_audio: bool = True,
    include_quality: bool = True,
    include_chapters: bool = True,
    include_colors: bool = True,
    output_srt: str | None = None,
    output_txt: str | None = None,
    output_md: str | None = None,
    output_json: str | None = None,
) -> dict[str, Any]:
    """Comprehensive video analysis — transcript, metadata, scenes, audio, quality, chapters, colors.

    Accepts a local file path or an HTTP/HTTPS URL. Direct video URLs
    (e.g. https://example.com/clip.mp4) are downloaded automatically.
    Streaming-platform URLs (YouTube, Vimeo, TikTok, Twitter/X, Instagram,
    Twitch, …) require yt-dlp (pip install yt-dlp).
    Each sub-analysis is independent so one failure will not abort the others.

    Args:
        input_path: Local path or HTTP/HTTPS URL to the video.
        whisper_model: Whisper model size (tiny, base, small, medium, large, turbo).
        language: Language code for transcription (auto-detect if None).
        scene_threshold: Scene change sensitivity 0.0-1.0.
        include_transcript: Run speech-to-text via Whisper (requires openai-whisper).
        include_scenes: Detect scene changes and boundaries.
        include_audio: Analyse audio waveform, peaks, and silence regions.
        include_quality: Run visual quality check.
        include_chapters: Auto-generate chapter markers from scene changes.
        include_colors: Extract dominant colors and extended metadata.
        output_srt: Optional path to write SRT subtitle file.
        output_txt: Optional path to write plain-text transcript.
        output_md: Optional path to write Markdown transcript with timestamps.
        output_json: Optional path to write full JSON transcript data.
    """
    if whisper_model not in VALID_WHISPER_MODELS:
        return _validation_error(f"Invalid model: must be one of {sorted(VALID_WHISPER_MODELS)}, got '{whisper_model}'")
    if not 0.0 <= scene_threshold <= 1.0:
        return _validation_error(f"scene_threshold must be between 0.0 and 1.0, got {scene_threshold}")
    from .ai_engine.download import _is_url

    if not _is_url(input_path):
        input_path = _validate_input_path(input_path)
    from .ai_engine import analyze_video

    return analyze_video(
        input_path,
        whisper_model=whisper_model,
        language=language,
        scene_threshold=scene_threshold,
        include_transcript=include_transcript,
        include_scenes=include_scenes,
        include_audio=include_audio,
        include_quality=include_quality,
        include_chapters=include_chapters,
        include_colors=include_colors,
        output_srt=output_srt,
        output_txt=output_txt,
        output_md=output_md,
        output_json=output_json,
    )


@mcp.tool()
@_safe_tool
def video_ai_scene_detect(
    input_path: str,
    threshold: float = 0.3,
    use_ai: bool = False,
) -> dict[str, Any]:
    """Detect scene changes in video."""
    if not 0.0 <= threshold <= 1.0:
        return _validation_error(f"threshold must be between 0.0 and 1.0, got {threshold}")
    input_path = _validate_input_path(input_path)
    from .ai_engine import ai_scene_detect

    return _result(ai_scene_detect(input_path, threshold, use_ai))


@mcp.tool()
@_safe_tool
def video_ai_stem_separation(
    input_path: str,
    output_dir: str,
    stems: list[str] | None = None,
    model: str = "htdemucs",
) -> dict[str, Any]:
    """Separate audio into stems using Demucs."""
    if model not in VALID_DEMUCS_MODELS:
        return _validation_error(f"Invalid model: must be one of {sorted(VALID_DEMUCS_MODELS)}, got '{model}'")
    if stems is not None and not isinstance(stems, list):
        return _validation_error(f"stems must be a list, got {type(stems).__name__}")
    input_path = _validate_input_path(input_path)
    from .ai_engine import ai_stem_separation

    return _result(ai_stem_separation(input_path, output_dir, stems, model))


@mcp.tool()
@_safe_tool
def video_ai_upscale(
    input_path: str,
    output_path: str,
    scale: int = 2,
    model: str = "realesrgan",
) -> dict[str, Any]:
    """Upscale video using AI super-resolution."""
    if scale not in {2, 4}:
        return _validation_error(f"scale must be 2 or 4, got {scale}")
    if model not in VALID_UPSCALE_MODELS:
        return _validation_error(f"Invalid model: must be one of {sorted(VALID_UPSCALE_MODELS)}, got '{model}'")
    input_path = _validate_input_path(input_path)
    from .ai_engine import ai_upscale

    return _result(ai_upscale(input_path, output_path, scale, model))


@mcp.tool()
@_safe_tool
def video_ai_color_grade(
    input_path: str,
    output_path: str,
    reference_path: str | None = None,
    style: str = "auto",
    lut_path: str | None = None,
) -> dict[str, Any]:
    """Apply a color grade to a video — by LUT file, style preset, or reference video.

    Args:
        input_path: Video file to grade.
        output_path: Where to write the graded video.
        reference_path: Optional reference video — when given, the video's
            color balance is adjusted to match the reference (overrides style).
        style: Style preset. One of: auto (gentle contrast lift), warm, cool,
            vintage, cinematic, dramatic, noir (high contrast, desaturated).
        lut_path: Optional .cube/.3dl LUT file applied with FFmpeg lut3d —
            overrides both reference and style for professional grading looks.
    """
    if style not in VALID_COLOR_GRADE_STYLES:
        return _validation_error(f"Invalid style: must be one of {sorted(VALID_COLOR_GRADE_STYLES)}, got '{style}'")
    input_path = _validate_input_path(input_path)
    if reference_path is not None:
        reference_path = _validate_input_path(reference_path)
    from .ai_engine import ai_color_grade

    return _result(ai_color_grade(input_path, output_path, reference_path, style, lut_path=lut_path))


@mcp.tool()
@_safe_tool
def video_quality_check(
    input_path: str,
    fail_on_warning: bool = False,
) -> dict[str, Any]:
    """Run visual quality checks on a video.

    Analyzes brightness, contrast, saturation, audio levels,
    and color balance. Returns quality scores and recommendations.

    Args:
        input_path: Absolute path to video file
        fail_on_warning: If True, treat warnings as failures
    """
    input_path = _validate_input_path(input_path)
    from .quality_guardrails import quality_check

    report = quality_check(input_path, fail_on_warning)
    if fail_on_warning and not report.get("all_passed", False):
        return _error_result(
            MCPVideoError(
                f"Quality gate failed: score {report.get('overall_score')} below release threshold",
                error_type="quality_error",
                code="quality_gate_failed",
                suggested_action={
                    "auto_fix": False,
                    "description": (
                        "Inspect storyboard/thumbnail, fix visual/audio issues, then rerun quality checks."
                    ),
                },
            )
        )
    return _result(report)


@mcp.tool()
@_safe_tool
def video_release_checkpoint(
    input_path: str,
    output_dir: str | None = None,
    min_score: float = DEFAULT_QUALITY_GATE_SCORE,
    frame_count: int = 6,
) -> dict[str, Any]:
    """Create preview artifacts only after the video passes quality gates.

    Use this before publishing or chaining more polish effects. It runs a hard
    quality gate, then writes a thumbnail and storyboard for human inspection.
    """
    if min_score < 0 or min_score > 100:
        return _validation_error(f"min_score must be 0-100, got {min_score}")
    if frame_count < 1:
        return _validation_error(f"frame_count must be at least 1, got {frame_count}")
    input_path = _validate_input_path(input_path)
    from .quality_guardrails import assert_quality
    from .engine_thumbnail import thumbnail
    from .engine_storyboard import storyboard

    report = assert_quality(input_path, min_score=min_score)
    review_dir = output_dir or f"{os.path.splitext(input_path)[0]}_release_review"
    os.makedirs(review_dir, exist_ok=True)
    thumb = thumbnail(input_path, output_path=os.path.join(review_dir, "thumbnail.jpg"))
    board = storyboard(input_path, output_dir=os.path.join(review_dir, "storyboard"), frame_count=frame_count)
    return _result(
        {
            "video": input_path,
            "quality": report,
            "thumbnail": thumb.frame_path,
            "storyboard": board.model_dump(),
            "review_required": True,
            "instructions": "Open the thumbnail/storyboard and inspect the final video before publishing.",
        }
    )


@mcp.tool()
@_safe_tool
def video_design_quality_check(
    input_path: str,
    auto_fix: bool = False,
    strict: bool = False,
) -> dict[str, Any]:
    """Run comprehensive design quality analysis on a video.

    Checks layout, typography, color, motion, and composition quality.
    Can automatically fix issues where possible.

    Args:
        input_path: Absolute path to video file
        auto_fix: If True, automatically apply fixes
        strict: If True, treat warnings as errors
    """
    input_path = _validate_input_path(input_path)
    from .design_quality import design_quality_check

    return _result(design_quality_check(input_path, auto_fix=auto_fix, strict=strict))


@mcp.tool()
@_safe_tool
def video_fix_design_issues(
    input_path: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Auto-fix design issues in a video.

    Applies automatic fixes for brightness, contrast, saturation,
    and audio level issues.

    Args:
        input_path: Absolute path to input video
        output_path: Absolute path for output (auto-generated if omitted)
    """
    input_path = _validate_input_path(input_path)
    from .design_quality import fix_design_issues

    return _result(fix_design_issues(input_path, output_path))
