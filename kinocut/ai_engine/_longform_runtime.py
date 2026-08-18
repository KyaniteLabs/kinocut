"""Per-chunk Whisper execution for long-form transcription."""

from __future__ import annotations

from contextlib import suppress
import os
from typing import Any

from ..errors import MCPVideoError
from ._longform_models import LongformChunk
from .transcribe import _extract_audio_segment, _format_json_transcript


def _format_chunk_result(result_data: dict[str, Any]) -> dict[str, Any]:
    """Normalize Whisper output while retaining its real word timing entries."""
    raw_segments = list(result_data.get("segments") or ())
    formatted = _format_json_transcript(
        str(result_data.get("text", "")).strip(),
        raw_segments,
        str(result_data.get("language", "unknown")),
    )
    for normalized, raw in zip(formatted["segments"], raw_segments, strict=True):
        normalized["words"] = list(raw.get("words") or ())
    return formatted


def _transcribe_chunk(
    video: str,
    chunk: LongformChunk,
    *,
    model: str,
    language: str | None,
    work_dir: str,
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
        try:
            import whisper  # type: ignore[import-not-found]
        except ImportError as exc:
            raise MCPVideoError(
                'Whisper not installed. Install with: pip install "kinocut[transcribe]"',
                error_type="dependency_error",
                code="missing_whisper",
                suggested_action={
                    "auto_fix": False,
                    "description": 'Run: pip install "kinocut[transcribe]" to enable transcription',
                },
            ) from exc
        whisper_model = whisper.load_model(model)
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
