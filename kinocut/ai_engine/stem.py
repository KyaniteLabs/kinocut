"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import importlib
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _get_video_duration, _run_command, _validate_input_path, _validate_output_path
from ..limits import DEFAULT_AI_TIMEOUT, DEFAULT_FFMPEG_TIMEOUT, MAX_AUDIO_DURATION
from ..validation import VALID_DEMUCS_MODELS

logger = logging.getLogger(__name__)


def _validate_demucs_model(model: str) -> None:
    if model not in VALID_DEMUCS_MODELS:
        raise MCPVideoError(
            f"Invalid model: must be one of {sorted(VALID_DEMUCS_MODELS)}, got {model!r}",
            error_type="validation_error",
            code="invalid_parameter",
        )


def _validate_stem_duration(video_path: str) -> None:
    duration = _get_video_duration(video_path)
    if duration > MAX_AUDIO_DURATION:
        raise MCPVideoError(
            f"Video duration ({duration:.0f}s) exceeds stem separation maximum of {MAX_AUDIO_DURATION}s",
            error_type="validation_error",
            code="duration_too_long",
        )


def ai_stem_separation(
    video: str,
    output_dir: str,
    stems: list[str] | None = None,
    model: str = "htdemucs",
) -> dict[str, str]:
    """Separate audio into stems using Demucs.

    Args:
        video: Input video path
        output_dir: Directory for output stem files
        stems: List of stems to extract (default: vocals, drums, bass, other)
        model: Demucs model to use (htdemucs, htdemucs_ft, etc.)

    Returns:
        Dict mapping stem names to file paths

    Raises:
        RuntimeError: If demucs is not installed
        FileNotFoundError: If video file doesn't exist
    """
    _validate_demucs_model(model)
    _validate_input_path(video)

    # Check for demucs availability
    try:
        importlib.import_module("demucs.separate")
    except ImportError:
        raise MCPVideoError(
            'Demucs not installed. Install with: pip install "mcp-video[stems]"',
            error_type="dependency_error",
            code="missing_demucs",
            suggested_action={
                "auto_fix": False,
                "description": 'Run: pip install "mcp-video[stems]" to enable stem separation',
            },
        ) from None

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)
    _validate_stem_duration(str(video_path))

    # Default stems if not provided
    stems = stems or ["vocals", "drums", "bass", "other"]

    # Create output directory
    _validate_output_path(output_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Step 1: Extract audio from video to temp WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        # Extract audio using ffmpeg: 16-bit PCM stereo (Demucs works best with stereo)
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
                "44100",  # 44.1kHz (CD quality)
                "-ac",
                "2",  # Stereo (Demucs expects stereo)
                audio_path,
            ],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )

        # Step 2: Run Demucs separation
        # Demucs outputs to: output_dir/model_name/audio_name/stem.wav
        audio_name = Path(audio_path).stem

        # Build demucs command arguments
        demucs_args = [
            "--out",
            str(output_path),
            "--name",
            model,
            audio_path,
        ]

        # Run demucs separation with a timeout.
        demucs_cmd = [sys.executable, "-m", "demucs.separate", *demucs_args]
        try:
            result = subprocess.run(demucs_cmd, capture_output=True, text=True, timeout=DEFAULT_AI_TIMEOUT)  # noqa: S603
        except subprocess.TimeoutExpired:
            raise ProcessingError(
                " ".join(demucs_cmd), -1, f"Demucs command timed out after {DEFAULT_AI_TIMEOUT}s"
            ) from None
        if result.returncode != 0:
            raise ProcessingError(" ".join(demucs_cmd), result.returncode, result.stderr)

        # Step 3: Collect output paths
        # Output structure: output_dir/model/audio_name/stem.wav
        model_output_dir = output_path / model / audio_name

        result_paths: dict[str, str] = {}
        for stem in stems:
            # Demucs outputs stems as stem.wav (e.g., vocals.wav, drums.wav)
            stem_file = model_output_dir / f"{stem}.wav"
            if stem_file.exists():
                result_paths[stem] = str(stem_file)

        return result_paths

    finally:
        # Clean up temp audio file
        Path(audio_path).unlink(missing_ok=True)
