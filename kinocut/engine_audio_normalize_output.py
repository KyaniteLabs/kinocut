"""Container selection and decoded-output validation for normalization."""

from __future__ import annotations

from pathlib import Path

from .defaults import AUDIO_NORMALIZE_OUTPUT_CODECS, AUDIO_NORMALIZE_VIDEO_CONTAINERS
from .engine_audio_validation import _run_audio_ffmpeg
from .errors import MCPVideoError
from .ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json
from .models import EditResult


class NormalizedAudioResult(EditResult):
    """A successful decoded output with the actual first audio codec."""

    audio_codec: str | None = None


def _normalization_codec(output: str) -> tuple[str, bool]:
    suffix = Path(output).suffix.lower()
    codec = AUDIO_NORMALIZE_OUTPUT_CODECS.get(suffix)
    if codec is None:
        raise MCPVideoError(
            "Unsupported audio normalization output container",
            error_type="validation_error",
            code="unsupported_normalization_container",
        )
    return codec, suffix in AUDIO_NORMALIZE_VIDEO_CONTAINERS


def _validate_normalized_output(path: str, codec: str | None, *, audio_only: bool = False) -> dict:
    """Require a real expected audio stream and a complete error-free decode."""
    probe = _run_ffprobe_json(path)
    stream = next((item for item in probe.get("streams", []) if item.get("codec_type") == "audio"), None)
    expected = {"libmp3lame": "mp3", "libopus": "opus", "libvorbis": "vorbis"}.get(codec, codec)
    if codec is not None and (stream is None or stream.get("codec_name") != expected):
        raise MCPVideoError(
            "Normalized output has an unexpected audio codec",
            error_type="processing_error",
            code="invalid_normalized_output",
        )
    selection = ["-map", "0:a:0", "-vn"] if audio_only else []
    decoded = _run_audio_ffmpeg(
        ["-v", "error", "-xerror", "-i", path, *selection, "-f", "null", "-"], runner=_run_ffmpeg
    )
    if decoded.stderr.strip():
        raise MCPVideoError(
            "Normalized output did not decode cleanly",
            error_type="processing_error",
            code="invalid_normalized_output",
        )
    return probe
