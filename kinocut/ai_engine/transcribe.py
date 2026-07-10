"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import _get_video_duration, _run_command, _seconds_to_srt_time, _validate_output_path
from ..limits import DEFAULT_FFMPEG_TIMEOUT, MAX_AI_TRANSCRIBE_DURATION
from ..validation import VALID_WHISPER_MODELS

logger = logging.getLogger(__name__)


def _validate_whisper_model(model: str) -> None:
    if model not in VALID_WHISPER_MODELS:
        raise MCPVideoError(
            f"Invalid model: must be one of {sorted(VALID_WHISPER_MODELS)}, got {model!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _validate_transcribe_duration(video_path: str) -> None:
    duration = _get_video_duration(video_path)
    if duration > MAX_AI_TRANSCRIBE_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds transcription maximum of {MAX_AI_TRANSCRIBE_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )


def ai_transcribe(
    video: str,
    output_srt: str | None = None,
    model: str = "base",
    language: str | None = None,
) -> dict[str, Any]:
    """Speech-to-text transcription using OpenAI Whisper.

    Args:
        video: Input video path
        output_srt: Optional output SRT file path
        model: Whisper model size (tiny, base, small, medium, large)
        language: Language code (auto-detect if None)

    Returns:
        Dict with transcript, segments, language

    Raises:
        RuntimeError: If whisper is not installed
        FileNotFoundError: If video file doesn't exist
    """
    _validate_whisper_model(model)
    if "\x00" in video:
        raise InputFileError(video, "Invalid path: contains null bytes")

    # Check for whisper availability
    try:
        import whisper
    except ImportError:
        raise MCPVideoError(
            'Whisper not installed. Install with: pip install "mcp-video[transcribe]"',
            error_type="dependency_error",
            code="missing_whisper",
            suggested_action={
                "auto_fix": False,
                "description": 'Run: pip install "mcp-video[transcribe]" to enable transcription',
            },
        ) from None

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)
    _validate_transcribe_duration(str(video_path))

    # Step 1: Extract audio to temp WAV file
    try:
        # Extract audio using ffmpeg: 16kHz mono 16-bit PCM (Whisper optimal format)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            audio_path = tmp.name

        _run_command(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",  # No video
                "-acodec",
                "pcm_s16le",  # 16-bit PCM
                "-ar",
                "16000",  # 16kHz (Whisper expects this)
                "-ac",
                "1",  # Mono
                audio_path,
            ],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )

        # Step 2: Load whisper model
        whisper_model = whisper.load_model(model)

        # Step 3: Transcribe with timestamps
        transcribe_options: dict[str, Any] = {}
        if language:
            transcribe_options["language"] = language

        result_data = whisper_model.transcribe(audio_path, **transcribe_options)

        # Step 4: Format as SRT if output_srt provided
        if output_srt:
            _validate_output_path(output_srt)
            srt_content = _format_srt(result_data.get("segments", []))
            Path(output_srt).write_text(srt_content, encoding="utf-8")

        # Step 5: Return dict with results
        return {
            "transcript": result_data.get("text", "").strip(),
            "segments": result_data.get("segments", []),
            "language": result_data.get("language", "unknown"),
        }

    finally:
        # Clean up temp audio file
        if "audio_path" in locals():
            Path(audio_path).unlink(missing_ok=True)


def _format_srt(segments: list[dict[str, Any]]) -> str:
    """Convert whisper segments to SRT format.

    SRT Format:
        1
        00:00:00,000 --> 00:00:02,000
        Hello world

        2
        00:00:02,000 --> 00:00:04,000
        Second line
    """
    srt_lines: list[str] = []
    index = 1

    for segment in segments:
        start_time = segment.get("start", 0.0)
        end_time = segment.get("end", 0.0)
        text = segment.get("text", "").strip()

        if not text:
            continue

        # Format: index, time range, text, blank line
        srt_lines.append(str(index))
        srt_lines.append(f"{_seconds_to_srt_time(start_time)} --> {_seconds_to_srt_time(end_time)}")
        srt_lines.append(text)
        srt_lines.append("")  # Blank line between entries
        index += 1

    return "\n".join(srt_lines)


def _format_txt(segments: list[dict[str, Any]]) -> str:
    """Convert Whisper segments to plain text (no timestamps)."""
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        if text:
            lines.append(text)
    return "\n".join(lines)


def _format_md(segments: list[dict[str, Any]]) -> str:
    """Convert Whisper segments to Markdown with inline timestamps.

    Format:
        **[00:00:01]** Hello world.
        **[00:00:03]** Second line.
    """
    lines = []
    for segment in segments:
        text = segment.get("text", "").strip()
        start = segment.get("start", 0.0)
        if text:
            # Reuse SRT formatter but drop milliseconds for readability
            ts = _seconds_to_srt_time(start).split(",")[0]
            lines.append(f"**[{ts}]** {text}")
    return "\n\n".join(lines)


def _format_json_transcript(
    transcript: str,
    segments: list[dict[str, Any]],
    language: str,
) -> dict[str, Any]:
    """Return structured JSON-serializable transcript data with full segment metadata."""
    return {
        "transcript": transcript,
        "language": language,
        "segment_count": len(segments),
        "segments": [
            {
                "id": seg.get("id", i),
                "start": seg.get("start", 0.0),
                "end": seg.get("end", 0.0),
                "text": seg.get("text", "").strip(),
                "tokens": seg.get("tokens", []),
                "avg_logprob": seg.get("avg_logprob"),
                "no_speech_prob": seg.get("no_speech_prob"),
            }
            for i, seg in enumerate(segments)
        ],
    }
