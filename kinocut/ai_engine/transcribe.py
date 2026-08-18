"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import math
import os
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


def _extract_audio_segment(
    video_path: str,
    start: float,
    duration: float,
    *,
    sample_rate: int = 16000,
    output_dir: str | None = None,
) -> str:
    """Extract a fixed-duration audio segment to a temp WAV file.

    Used by the long-form transcription workflow to slice media up to
    MAX_VIDEO_DURATION into per-chunk WAV files for Whisper.  Output is
    Whisper-optimal 16-bit mono PCM at the requested sample rate.

    Returns the path of the generated WAV file.  The caller is responsible
    for cleanup (long-form paths use a single temp dir per run).
    """
    if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
        raise MCPVideoError(
            f"start must be a non-negative number, got {start!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(duration)
        or duration <= 0
    ):
        raise MCPVideoError(
            f"duration must be a positive number, got {duration!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, int) or sample_rate <= 0:
        raise MCPVideoError(
            f"sample_rate must be a positive int, got {sample_rate!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    out_fd, out_path = tempfile.mkstemp(suffix=".wav", prefix="kc_longform_", dir=output_dir)
    os.close(out_fd)

    try:
        _run_command(
            [
                "ffmpeg",
                "-y",
                "-ss",
                f"{float(start):.6f}",
                "-i",
                str(video_path),
                "-t",
                f"{float(duration):.6f}",
                "-vn",
                "-acodec",
                "pcm_s16le",
                "-ar",
                str(sample_rate),
                "-ac",
                "1",
                out_path,
            ],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except Exception:
        Path(out_path).unlink(missing_ok=True)
        raise
    return out_path


def _extract_transcription_audio(video_path: Path, audio_path: str) -> None:
    """Extract audio from video to 16kHz mono 16-bit PCM WAV for Whisper."""
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


def _build_transcription_result(result_data: dict[str, Any]) -> dict[str, Any]:
    """Build the transcription result dict from Whisper output."""
    return {
        "transcript": result_data.get("text", "").strip(),
        "segments": result_data.get("segments", []),
        "language": result_data.get("language", "unknown"),
    }


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
            'Whisper not installed. Install with: pip install "kinocut[transcribe]"',
            error_type="dependency_error",
            code="missing_whisper",
            suggested_action={
                "auto_fix": False,
                "description": 'Run: pip install "kinocut[transcribe]" to enable transcription',
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

        _extract_transcription_audio(video_path, audio_path)

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

        return _build_transcription_result(result_data)

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
