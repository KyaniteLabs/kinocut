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
from pathlib import Path
from typing import Any

from ..defaults import DEFAULT_FFMPEG_TIMEOUT
from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _validate_input_path


def add_generated_audio(
    video: str,
    audio_config: dict[str, Any],
    output: str,
) -> str:
    """Add generated audio to a video file.

    Args:
        video: Input video path
        audio_config: Configuration dict with:
            - drone: {"frequency", "volume"} for background drone
            - events: List of timed events [{"type", "at", ...}]
        output: Output video path

    Returns:
        Path to output video
    """
    import subprocess
    import tempfile

    # Generate audio sequence
    events = audio_config.get("events", [])

    # Add drone if specified
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

    # Create temp audio file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    # Input validation before FFmpeg
    _validate_input_path(video)
    if not os.path.isfile(video):
        raise InputFileError(video)

    try:
        # Generate audio
        audio_sequence(events, audio_path)

        # Mix with video using FFmpeg
        out_dir = os.path.dirname(output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-i",
            audio_path,
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-shortest",
            output,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.TimeoutExpired:
            raise ProcessingError(
                " ".join(cmd), -1, f"Audio processing command timed out after {DEFAULT_FFMPEG_TIMEOUT}s"
            ) from None
        if result.returncode != 0:
            raise ProcessingError(" ".join(cmd), result.returncode, result.stderr)

        return output

    finally:
        Path(audio_path).unlink(missing_ok=True)
