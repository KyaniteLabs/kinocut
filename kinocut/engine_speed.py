"""Playback speed operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _atomic_output, _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg, _sanitize_ffmpeg_number
from .errors import MCPVideoError
from .limits import MAX_SPEED_CHAIN_COUNT, MIN_SPEED_FACTOR, MAX_SPEED_FACTOR, MAX_VIDEO_DURATION
from .models import EditResult


def _speed_audio_filter(factor: float) -> str:
    """Split slow playback into supported atempo stages within the public bound."""
    if factor >= 0.5:
        return f"atempo={factor}"
    chain_count = 2
    while factor ** (1 / chain_count) < 0.5:
        chain_count += 1
        if chain_count > MAX_SPEED_CHAIN_COUNT:
            raise MCPVideoError("Speed requires too many audio filters", error_type="validation_error")
    return ",".join([f"atempo={factor ** (1 / chain_count)}"] * chain_count)


def speed(
    input_path: str,
    factor: float = 1.0,
    output_path: str | None = None,
) -> EditResult:
    """Change playback speed. factor > 1 = faster, < 1 = slower."""
    input_path = _validate_input_path(input_path)
    factor = _sanitize_ffmpeg_number(factor, "factor")
    if not MIN_SPEED_FACTOR <= factor <= MAX_SPEED_FACTOR:
        raise MCPVideoError(
            f"Speed factor must be between {MIN_SPEED_FACTOR} and {MAX_SPEED_FACTOR}",
            error_type="validation_error",
            code="speed_out_of_range",
        )

    output = output_path or _auto_output(input_path, f"speed_{factor}x")
    _validate_output_path(output)

    # Use setpts for video, atempo for audio
    video_filter = f"setpts={1 / factor}*PTS"
    audio_filter = _speed_audio_filter(factor)

    # Check if input has audio
    info = probe(input_path)
    if info.duration / factor > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            "Speed-adjusted video exceeds the supported duration",
            error_type="validation_error",
            code="duration_too_long",
        )
    has_audio = info.audio_codec is not None

    with _atomic_output(output) as staged:
        _validate_output_path(staged)
        with _timed_operation() as timing:
            if has_audio:
                _run_ffmpeg(
                    _build_ffmpeg_cmd(
                        input_path,
                        output_path=staged,
                        extra=[
                            "-filter_complex",
                            f"[0:v]{video_filter}[v];[0:a]{audio_filter}[a]",
                            "-map",
                            "[v]",
                            "-map",
                            "[a]",
                        ],
                    )
                )
            else:
                _run_ffmpeg(
                    _build_ffmpeg_cmd(
                        input_path,
                        output_path=staged,
                        video_filter=video_filter,
                        audio_codec=None,
                        extra=["-an"],
                    )
                )
        result = _build_edit_result(staged, "speed", timing)

    return result.model_copy(update={"output_path": output})
