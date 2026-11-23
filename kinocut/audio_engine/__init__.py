"""Audio synthesis and sound design engine.

Pure NumPy-based audio generation with no external dependencies.
"""

from __future__ import annotations

# Re-exports for backward compatibility
from .core import (
    apply_envelope as apply_envelope,
    apply_fade as apply_fade,
    apply_highpass as apply_highpass,
    apply_lowpass as apply_lowpass,
    apply_reverb as apply_reverb,
    generate_noise as generate_noise,
    generate_sawtooth as generate_sawtooth,
    generate_sine as generate_sine,
    generate_square as generate_square,
    generate_triangle as generate_triangle,
    write_wav as write_wav,
)
from .sequencing import audio_compose as audio_compose, audio_effects as audio_effects, audio_sequence as audio_sequence
from .synthesis import audio_preset as audio_preset, audio_synthesize as audio_synthesize

# This is defined in __init__.py itself to avoid circular imports
# add_generated_audio is re-exported at module level below

import os
from typing import Any

from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _validate_input_path


def _build_audio_events(audio_config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the event list from config, inserting a drone if specified."""
    events = list(audio_config.get("events", []))

    drone_config = audio_config.get("drone")
    if drone_config:
        events.insert(
            0,
            {
                "type": "tone",
                "at": 0,
                "duration": 60,  # Will be truncated to video length
                "freq": drone_config.get("frequency", 100),
                "volume": drone_config.get("volume", 0.2),
                "waveform": "sine",
            },
        )

    if not events:
        raise MCPVideoError("No audio events specified", error_type="validation_error", code="invalid_parameter")
    return events


def _has_audio_stream(video_path: str) -> bool:
    """True when the video already carries an audio track the output must keep."""
    from ..engine_runtime_utils import _has_audio
    from ..ffmpeg_helpers import _run_ffprobe_json

    return _has_audio(_run_ffprobe_json(video_path))


def _generated_audio_args(video_path: str, audio_path: str, mix_with_source: bool, video_duration: float) -> list[str]:
    """Build the FFmpeg arguments that lay the generated track over the picture.

    Explicit ``-map`` selections are mandatory: FFmpeg's default stream
    selection would pick the video's own audio over the generated file. The
    generated track is padded with silence and the output is cut to the video
    duration, so a short sequence never shortens the picture. When the source
    has audio, the generated track is summed under it instead of replacing it.
    """
    args = ["-xerror", "-i", video_path, "-i", audio_path]
    if mix_with_source:
        filter_complex = (
            "[0:a:0]aresample=async=1:first_pts=0[a0];"
            "[1:a:0]aresample=async=1:first_pts=0[a1];"
            "[a0][a1]amix=inputs=2:duration=longest:normalize=0,apad[aout]"
        )
        args.extend(["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[aout]"])
    else:
        args.extend(["-map", "0:v:0", "-map", "1:a:0", "-af", "apad"])
    args.extend(["-c:v", "copy", "-c:a", "aac", "-t", f"{video_duration:.6f}"])
    return args


def _require_generated_audio(path: str) -> None:
    """Fail before publication when the render does not carry the generated track."""
    from ..engine_audio_validation import _run_audio_ffmpeg
    from ..ffmpeg_helpers import _run_ffmpeg, _run_ffprobe_json

    streams = _run_ffprobe_json(path).get("streams", [])
    if not any(stream.get("codec_type") == "audio" and stream.get("codec_name") == "aac" for stream in streams):
        raise ProcessingError("ffmpeg", 1, "", reason="rendered output has no generated AAC audio stream")
    decoded = _run_audio_ffmpeg(
        ["-v", "error", "-xerror", "-i", path, "-map", "0:a:0", "-vn", "-f", "null", "-"],
        runner=_run_ffmpeg,
    )
    if decoded.stderr.strip():
        raise ProcessingError(
            "ffmpeg", decoded.returncode, decoded.stderr, reason="rendered audio did not decode cleanly"
        )


def add_generated_audio(
    video: str,
    audio_config: dict[str, Any],
    output: str,
) -> str:
    """Lay procedurally generated audio over a video.

    The output keeps the video's full duration. A video that already has audio
    keeps it: the generated track is mixed underneath. A silent video receives
    the generated track as its only audio.

    Args:
        video: Input video path
        audio_config: Configuration dict with:
            - drone: {"frequency", "volume"} for background drone
            - events: List of timed events [{"type", "at", ...}]
        output: Output video path

    Returns:
        Path to output video
    """
    import tempfile

    from ..engine_runtime_utils import _movflags_args
    from ..ffmpeg_helpers import _atomic_output, _get_video_duration, _run_ffmpeg, _validate_output_path

    events = _build_audio_events(audio_config)

    video_path = _validate_input_path(video)
    _validate_output_path(output)
    video_duration = _get_video_duration(video_path)
    mix_with_source = _has_audio_stream(video_path)

    with tempfile.TemporaryDirectory(prefix="kinocut-generated-audio-") as scratch:
        audio_path = os.path.join(scratch, "generated.wav")
        audio_sequence(events, audio_path)
        args = _generated_audio_args(video_path, audio_path, mix_with_source, video_duration)
        args.extend(_movflags_args(output))
        with _atomic_output(output) as staged:
            _run_ffmpeg([*args, staged])
            _require_generated_audio(staged)

    return output
