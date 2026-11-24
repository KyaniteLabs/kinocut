"""Per-chunk Whisper execution for long-form transcription."""

from __future__ import annotations

from contextlib import suppress
import os
from typing import Any

from ._longform_merge import _validate_chunk_result_shape
from ._longform_models import LongformChunk
from .transcribe import _extract_audio_segment, _format_json_transcript, _import_whisper, _load_whisper_model


def _format_chunk_result(result_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Whisper output while retaining real word timings and raw segment metadata."""
    _validate_chunk_result_shape(result_data)
    raw_segments = [segment for segment in result_data.get("segments") or () if isinstance(segment, dict)]
    formatted = _format_json_transcript(
        str(result_data.get("text", "")).strip(),
        raw_segments,
        str(result_data.get("language", "unknown")),
    )
    for normalized, raw in zip(formatted["segments"], raw_segments, strict=True):
        for key, value in raw.items():
            if key not in normalized:
                normalized[key] = value
        normalized["words"] = list(raw.get("words") or ())
    return formatted


def _transcribe_chunk(
    video: str,
    chunk: LongformChunk,
    *,
    model: str,
    language: str | None,
    work_dir: str,
    model_cache: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract and locally transcribe one chunk; always remove its temporary WAV."""
    audio_path: str | None = None
    try:
        audio_path = _extract_audio_segment(
            video,
            chunk.start,
            chunk.duration,
            output_dir=work_dir,
        )
        whisper_model = model_cache.get(model) if model_cache is not None else None
        if whisper_model is None:
            whisper_model = _load_whisper_model(_import_whisper(model), model)
            if model_cache is not None:
                model_cache[model] = whisper_model
        options: dict[str, Any] = {"word_timestamps": True, "task": "transcribe"}
        if language:
            options["language"] = language
        result = whisper_model.transcribe(audio_path, **options)
        return _format_chunk_result(result)
    finally:
        if audio_path is not None:
            with suppress(OSError):
                os.unlink(audio_path)


__all__ = ["_format_chunk_result", "_transcribe_chunk"]
