"""CLI handlers for AI-powered video commands."""

from __future__ import annotations

from typing import Any

from .common import _with_spinner
from .formatting import (
    _format_ai_color_grade,
    _format_ai_remove_silence,
    _format_ai_scene_detect,
    _format_ai_stem_separation,
    _format_ai_transcribe,
    _format_ai_upscale,
    _format_video_analyze,
)
from .runner import CommandRunner, _out


def handle_ai_commands(args: Any, *, use_json: bool) -> bool:
    """Handle AI video commands extracted from the main dispatcher."""
    runner = CommandRunner(args, use_json)

    def _transcribe(a, j):
        from ..ai_engine import ai_transcribe

        r = _with_spinner(
            "Transcribing...",
            ai_transcribe,
            a.input,
            output_srt=a.output,
            model=a.model,
            language=a.language,
        )
        _out(r, j, lambda res: _format_ai_transcribe(res, a.output))

    runner.register("video-ai-transcribe", _transcribe)

    def _analyze(a, j):
        from ..ai_engine import analyze_video

        r = _with_spinner(
            "Analysing video...",
            analyze_video,
            a.input,
            whisper_model=a.model,
            language=a.language,
            scene_threshold=a.scene_threshold,
            include_transcript=not a.no_transcript,
            include_scenes=not a.no_scenes,
            include_audio=not a.no_audio,
            include_quality=not a.no_quality,
            include_chapters=not a.no_chapters,
            include_colors=not a.no_colors,
            output_srt=a.output_srt,
            output_txt=a.output_txt,
            output_md=a.output_md,
            output_json=a.output_json,
        )
        _out(r, j, lambda res: _format_video_analyze(res, a.no_transcript))

    runner.register("video-analyze", _analyze)

    def _upscale(a, j):
        from ..ai_engine import ai_upscale

        r = _with_spinner("Upscaling...", ai_upscale, a.input, a.output, scale=a.scale, model=a.model)
        _out(
            r,
            j,
            lambda res: _format_ai_upscale(res, a.scale),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-ai-upscale", _upscale)

    def _stem_sep(a, j):
        from ..ai_engine import ai_stem_separation

        r = _with_spinner(
            "Separating stems...",
            ai_stem_separation,
            a.input,
            a.output_dir,
            stems=a.stems,
            model=a.model,
        )
        _out(r, j, _format_ai_stem_separation, json_transform=lambda r: r if isinstance(r, dict) else {"stems": r})

    runner.register("video-ai-stem-separation", _stem_sep)

    def _scene_detect(a, j):
        from ..ai_engine import ai_scene_detect

        r = _with_spinner("Detecting scenes (AI)...", ai_scene_detect, a.input, threshold=a.threshold, use_ai=a.use_ai)
        _out(r, j, _format_ai_scene_detect, json_transform=lambda r: r if isinstance(r, dict) else {"scenes": r})

    runner.register("video-ai-scene-detect", _scene_detect)

    def _color_grade(a, j):
        from ..ai_engine import ai_color_grade

        r = _with_spinner("Color grading...", ai_color_grade, a.input, a.output, reference=a.reference, style=a.style)
        _out(
            r,
            j,
            lambda res: _format_ai_color_grade(res, a.style),
            json_transform=lambda r: {"success": True, "output_path": r},
        )

    runner.register("video-ai-color-grade", _color_grade)

    def _remove_silence(a, j):
        from ..ai_engine import ai_remove_silence

        r = _with_spinner(
            "Removing silence...",
            ai_remove_silence,
            a.input,
            a.output,
            silence_threshold=a.silence_threshold,
            min_silence_duration=a.min_silence_duration,
            keep_margin=a.keep_margin,
        )
        _out(r, j, _format_ai_remove_silence, json_transform=lambda r: {"success": True, "output_path": r})

    runner.register("video-ai-remove-silence", _remove_silence)

    return runner.dispatch()
