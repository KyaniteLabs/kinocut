"""Playback speed operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _timed_operation
from .paths import _auto_output
from .ffmpeg_helpers import _run_ffmpeg, _sanitize_ffmpeg_number
from .errors import MCPVideoError
from .limits import MAX_SPEED_CHAIN_COUNT
from .models import EditResult


def speed(
    input_path: str,
    factor: float = 1.0,
    output_path: str | None = None,
) -> EditResult:
    """Change playback speed. factor > 1 = faster, < 1 = slower."""
    input_path = _validate_input_path(input_path)
    factor = _sanitize_ffmpeg_number(factor, "factor")
    if factor <= 0:
        raise MCPVideoError("Speed factor must be positive")

    output = output_path or _auto_output(input_path, f"speed_{factor}x")
    _validate_output_path(output)

    # Use setpts for video, atempo for audio
    video_filter = f"setpts={1 / factor}*PTS"
    audio_filter = f"atempo={factor}"

    # atempo only supports 0.5 to 100.0; chain if needed
    if factor < 0.5:
        chain_count = 2
        while factor ** (1 / chain_count) < 0.5:
            chain_count += 1
            if chain_count > MAX_SPEED_CHAIN_COUNT:
                raise MCPVideoError(
                    "Speed factor too extreme: would require more than 20 atempo filters",
                    error_type="validation_error",
                    code="invalid_parameter",
                )
        tempo_val = factor ** (1 / chain_count)
        audio_filter = ",".join([f"atempo={tempo_val}"] * chain_count)
    elif factor > 100:
        chain_count = 2
        while factor ** (1 / chain_count) > 100:
            chain_count += 1
            if chain_count > MAX_SPEED_CHAIN_COUNT:
                raise MCPVideoError(
                    "Speed factor too extreme: would require more than 20 atempo filters",
                    error_type="validation_error",
                    code="invalid_parameter",
                )
        tempo_val = factor ** (1 / chain_count)
        audio_filter = ",".join([f"atempo={tempo_val}"] * chain_count)

    # Check if input has audio
    info = probe(input_path)
    has_audio = info.audio_codec is not None

    with _timed_operation() as timing:
        if has_audio:
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=output,
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
                    output_path=output,
                    video_filter=video_filter,
                    audio_codec=None,
                    extra=["-an"],
                )
            )

    return _build_edit_result(
        output,
        "speed",
        timing,
    )
