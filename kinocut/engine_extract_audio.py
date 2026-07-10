"""Audio extraction operation for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError


def extract_audio(
    input_path: str,
    output_path: str | None = None,
    format: str = "mp3",
) -> str:
    """Extract audio track from a video file."""
    VALID_AUDIO_FORMATS = {"mp3", "aac", "wav", "ogg", "flac"}
    if format not in VALID_AUDIO_FORMATS:
        raise MCPVideoError(
            f"Invalid audio format: {format}. Must be one of {VALID_AUDIO_FORMATS}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    input_path = _validate_input_path(input_path)
    ext = f".{format}" if not format.startswith(".") else format
    output = output_path or _auto_output(input_path, "audio", ext=ext)
    _validate_output_path(output)

    codec_map = {
        "mp3": "libmp3lame",
        "aac": "aac",
        "wav": "pcm_s16le",
        "ogg": "libvorbis",
        "flac": "flac",
    }
    codec = codec_map[format]

    _run_ffmpeg(
        [
            "-i",
            input_path,
            "-vn",
            "-c:a",
            codec,
            "-b:a",
            "192k" if format != "wav" else "0",
            "-y",
            output,
        ]
    )

    return output
