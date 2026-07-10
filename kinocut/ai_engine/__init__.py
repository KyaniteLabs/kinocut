"""AI-powered video processing using machine learning models."""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any
from collections.abc import Callable

from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import _validate_output_path

# Public API re-exports
from .color import ai_color_grade as ai_color_grade
from .download import _resolve_video_source as _resolve_video_source
from .scene import ai_scene_detect as ai_scene_detect
from .silence import ai_remove_silence as ai_remove_silence
from .spatial import audio_spatial as audio_spatial
from .stem import ai_stem_separation as ai_stem_separation
from .transcribe import ai_transcribe as ai_transcribe
from .upscale import ai_upscale as ai_upscale

# Private helper re-exports for tests
from .download import _is_url as _is_url, _url_host as _url_host
import subprocess  # noqa: F401

from .spatial import (
    _azimuth_to_pan as _azimuth_to_pan,
    _elevation_to_volume as _elevation_to_volume,
    _standard_scene_detect as _standard_scene_detect,
)
from .upscale import _ai_upscale_opencv as _ai_upscale_opencv
from .download import _is_safe_url as _is_safe_url
from .transcribe import (
    _format_json_transcript as _format_json_transcript,
    _format_md as _format_md,
    _format_srt as _format_srt,
    _format_txt as _format_txt,
)

logger = logging.getLogger(__name__)


def _validate_analysis_output_paths(
    output_srt: str | None,
    output_txt: str | None,
    output_md: str | None,
    output_json: str | None,
) -> None:
    for path in (output_srt, output_txt, output_md, output_json):
        if path is not None:
            _validate_output_path(path)


def _run_analysis(
    name: str,
    fn: Callable[..., Any],
    errors: list[dict[str, str]],
    *args: Any,
    fallback: Any | None = None,
    **kwargs: Any,
) -> Any | None:
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("Analysis section %s failed: %s", name, exc)
        errors.append({"section": name, "error": str(exc)})
        return fallback


def _probe_media(video_path: Path, _engine: Any) -> dict[str, Any]:
    info = _engine.probe(str(video_path))
    return {
        "duration": info.duration,
        "width": info.width,
        "height": info.height,
        "fps": info.fps,
        "codec": info.codec,
        "audio_codec": info.audio_codec,
        "audio_sample_rate": info.audio_sample_rate,
        "bitrate": info.bitrate,
        "size_bytes": info.size_bytes,
        "format": info.format,
    }


def _waveform_to_dict(waveform: Any) -> dict[str, Any]:
    return {
        "duration": waveform.duration,
        "peaks": waveform.peaks,
        "mean_level": waveform.mean_level,
        "max_level": waveform.max_level,
        "min_level": waveform.min_level,
        "silence_regions": waveform.silence_regions,
    }


def _extract_video_colors(video_path: Path, n_colors: int = 5) -> dict[str, Any]:
    """Extract dominant colors for analyze_video using the image engine's video-frame support."""
    from ..image_engine import extract_colors

    result = extract_colors(str(video_path), n_colors=n_colors)
    return result.model_dump() if hasattr(result, "model_dump") else dict(result)


def _build_transcript_result(
    video_path: Path,
    *,
    output_srt: str | None,
    output_txt: str | None,
    output_md: str | None,
    output_json: str | None,
    whisper_model: str,
    language: str | None,
) -> dict[str, Any]:
    raw = ai_transcribe(
        str(video_path),
        output_srt=output_srt,
        model=whisper_model,
        language=language,
    )
    segments = raw.get("segments", [])
    txt_path: str | None = None
    md_path: str | None = None
    json_path: str | None = None

    if output_txt:
        _validate_output_path(output_txt)
        Path(output_txt).write_text(_format_txt(segments), encoding="utf-8")
        txt_path = output_txt
    if output_md:
        _validate_output_path(output_md)
        Path(output_md).write_text(_format_md(segments), encoding="utf-8")
        md_path = output_md
    if output_json:
        _validate_output_path(output_json)
        json_data = _format_json_transcript(
            raw.get("transcript", ""),
            segments,
            raw.get("language", "unknown"),
        )
        Path(output_json).write_text(
            json.dumps(json_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        json_path = output_json

    return {
        "text": raw.get("transcript", ""),
        "language": raw.get("language", "unknown"),
        "segments": segments,
        "srt_path": output_srt,
        "txt_path": txt_path,
        "md_path": md_path,
        "json_path": json_path,
    }


def analyze_video(
    video: str,
    *,
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

    Accepts either a **local file path** or an **HTTP/HTTPS URL**.

    For direct video URLs (e.g. ``https://example.com/clip.mp4``) the file is
    downloaded automatically via ``urllib``.  For streaming-platform URLs
    (YouTube, Vimeo, TikTok, Twitter/X, Instagram, Twitch, …) the optional
    ``yt-dlp`` package is used — install it with ``pip install yt-dlp``.

    Each sub-analysis is independent: one failure will not abort the others.

    Args:
        video: Local path **or** HTTP/HTTPS URL to the video.
        whisper_model: Whisper model size (tiny, base, small, medium, large, turbo).
        language: Language code for transcription (auto-detect if None).
        scene_threshold: Scene change sensitivity 0.0-1.0 (lower = more sensitive).
        include_transcript: Run speech-to-text via Whisper (requires openai-whisper).
        include_scenes: Detect scene changes and boundaries.
        include_audio: Analyse audio waveform, peaks, and silence regions.
        include_quality: Run visual quality check (brightness, contrast, saturation, audio levels).
        include_chapters: Auto-generate chapter markers from scene changes.
        include_colors: Extract dominant colors and extended metadata.
        output_srt: Optional path to write SRT subtitle file.
        output_txt: Optional path to write plain-text transcript.
        output_md: Optional path to write Markdown transcript with timestamps.
        output_json: Optional path to write full JSON transcript data.

    Returns:
        Dict with keys: success, video, source_url, metadata, transcript, scenes,
        audio, chapters, colors, quality, errors.
    """
    if "\x00" in video:
        raise InputFileError(video, "Invalid path: contains null bytes")
    if not (0.0 <= scene_threshold <= 1.0):
        raise MCPVideoError(
            f"scene_threshold must be between 0.0 and 1.0, got {scene_threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    _validate_analysis_output_paths(output_srt, output_txt, output_md, output_json)

    _tmp_dir: str | None = None
    try:
        local_video, _tmp_dir, source_url = _resolve_video_source(video)
        video_path = Path(local_video)
        if not video_path.exists():
            raise InputFileError(str(video_path))

        from .. import engine as _engine
        from .. import effects_engine as _effects
        from .. import quality_guardrails as _quality

        errors: list[dict[str, str]] = []

        metadata = _run_analysis(
            "metadata",
            lambda vp: {"path": str(vp.resolve()), **_probe_media(vp, _engine)},
            errors,
            video_path,
            fallback={"path": str(video_path.resolve())},
        )

        transcript_result = (
            _run_analysis(
                "transcript",
                _build_transcript_result,
                errors,
                video_path,
                output_srt=output_srt,
                output_txt=output_txt,
                output_md=output_md,
                output_json=output_json,
                whisper_model=whisper_model,
                language=language,
            )
            if include_transcript
            else None
        )

        def _scenes():
            return _engine.detect_scenes(str(video_path), threshold=scene_threshold).scenes

        def _chapters():
            raw = _effects.auto_chapters(str(video_path), threshold=scene_threshold)
            return [{"timestamp": ts, "title": title} for ts, title in raw]

        analyses = [
            ("scenes", include_scenes, _scenes),
            ("audio", include_audio, lambda: _waveform_to_dict(_engine.audio_waveform(str(video_path)))),
            ("chapters", include_chapters, _chapters),
            ("colors", include_colors, lambda: _extract_video_colors(video_path)),
            ("quality", include_quality, lambda: _quality.quality_check(str(video_path))),
        ]
        results = {name: (_run_analysis(name, fn, errors) if flag else None) for name, flag, fn in analyses}

        return {
            "success": True,
            "video": str(video_path.resolve()),
            "source_url": source_url,
            "metadata": metadata,
            "transcript": transcript_result,
            **results,
            "errors": errors,
        }

    finally:
        if _tmp_dir is not None:
            shutil.rmtree(_tmp_dir, ignore_errors=True)
