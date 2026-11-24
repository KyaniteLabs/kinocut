"""Audio extraction operation for the FFmpeg engine."""

from __future__ import annotations

from .errors import MCPVideoError
from .ffmpeg_helpers import _atomic_output, _run_ffmpeg, _run_ffprobe_json, _validate_input_path, _validate_output_path
from .paths import _auto_output
from .validation_errors import rejected_value


def _verify_extracted_audio(path: str) -> None:
    metadata = _run_ffprobe_json(path)
    if not any(stream.get("codec_type") == "audio" for stream in metadata.get("streams", [])):
        raise MCPVideoError(
            "Extracted output has no audio stream", error_type="processing_error", code="invalid_extracted_audio"
        )
    decoded = _run_ffmpeg(
        ["-v", "error", "-xerror", "-i", path, "-map", "0:a:0", "-abort_on", "empty_output", "-f", "null", "-"]
    )
    if decoded.stderr.strip():
        raise MCPVideoError(
            "Extracted audio did not decode cleanly", error_type="processing_error", code="invalid_extracted_audio"
        )


def extract_audio(
    input_path: str,
    output_path: str | None = None,
    format: str = "mp3",
) -> str:
    """Extract audio track from a video file."""
    VALID_AUDIO_FORMATS = {"mp3", "aac", "wav", "ogg", "flac"}
    if format not in VALID_AUDIO_FORMATS:
        raise MCPVideoError(
            f"Invalid audio format: {rejected_value(format)}. Must be one of {VALID_AUDIO_FORMATS}",
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

    with _atomic_output(output) as staged:
        _run_ffmpeg(
            ["-xerror", "-i", input_path, "-vn", "-c:a", codec, "-b:a", "192k" if format != "wav" else "0", staged]
        )
        _verify_extracted_audio(staged)

    return output
