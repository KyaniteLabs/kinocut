"""Playback speed operations for the FFmpeg engine."""

from __future__ import annotations

from .ffmpeg_helpers import _build_ffmpeg_cmd
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .engine_probe import probe
from .engine_runtime_utils import _build_edit_result, _transactional_edit
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

    # Use PTS-STARTPTS so non-zero start_time clips do not drift; ensure even dims for libx264
    video_filter = rf"setpts=(PTS-STARTPTS)/{factor},pad=iw+mod(iw\,2):ih+mod(ih\,2)"
    audio_filter = _speed_audio_filter(factor)

    # Check if input has audio (and how many audio tracks to preserve)
    info = probe(input_path)
    if info.duration / factor > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            "Speed-adjusted video exceeds the supported duration",
            error_type="validation_error",
            code="duration_too_long",
        )
    has_audio = info.audio_codec is not None
    audio_tracks = max(1, getattr(info, "audio_stream_count", 1) or 1) if has_audio else 0

    def render(staged: str) -> None:
        if has_audio:
            audio_chains = [f"[0:a:{idx}]{audio_filter}[a{idx}]" for idx in range(audio_tracks)]
            audio_maps = [item for idx in range(audio_tracks) for item in ("-map", f"[a{idx}]")]
            filter_graph = ";".join([f"[0:v]{video_filter}[v]", *audio_chains])
            _run_ffmpeg(
                _build_ffmpeg_cmd(
                    input_path,
                    output_path=staged,
                    extra=[
                        "-filter_complex",
                        filter_graph,
                        "-map",
                        "[v]",
                        *audio_maps,
                        "-pix_fmt",
                        "yuv420p",
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
                    extra=["-an", "-pix_fmt", "yuv420p"],
                )
            )

    return _transactional_edit(
        output, "speed", render, build_result=lambda staged: _build_edit_result(staged, "speed", {"elapsed_ms": None})
    )
