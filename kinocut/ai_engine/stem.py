"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import importlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .._install_hints import pip_install_hint
from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import (
    _atomic_output,
    _get_video_duration,
    _open_staged_writer,
    _run_command,
    _validate_input_path,
    _validate_output_path,
)
from ..limits import DEFAULT_AI_TIMEOUT, DEFAULT_FFMPEG_TIMEOUT, MAX_AUDIO_DURATION
from ..offline import is_offline_mode
from ..process_tree import sanitized_subprocess_env
from ..publication import validate_artifact_location
from ..validation import VALID_DEMUCS_MODELS
from ..validation_errors import rejected_value

logger = logging.getLogger(__name__)


def _validate_demucs_model(model: str) -> None:
    if model not in VALID_DEMUCS_MODELS:
        raise MCPVideoError(
            f"Invalid model: must be one of {sorted(VALID_DEMUCS_MODELS)}, got {rejected_value(model)!r}",
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


def _extract_stem_audio(video_path: Path, audio_path: str) -> None:
    """Extract audio from video to 16-bit PCM stereo WAV for Demucs."""
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


def _run_demucs_separation(
    audio_path: str,
    output_path: Path,
    model: str,
    stems: list[str],
) -> dict[str, str]:
    """Run Demucs separation in a private staging dir and publish stems atomically."""
    audio_name = Path(audio_path).stem
    final_model_dir = output_path / model / audio_name
    destinations = {stem: final_model_dir / f"{stem}.wav" for stem in stems}
    # Pre-validate every stem target so default overwrite=False refuses before running Demucs.
    for dest in destinations.values():
        _validate_output_path(str(dest))

    with tempfile.TemporaryDirectory(prefix="kinocut-stems-") as stage_dir:
        demucs_args = [
            "--out",
            stage_dir,
            "--name",
            model,
            audio_path,
        ]
        demucs_cmd = [sys.executable, "-m", "demucs.separate", *demucs_args]
        try:
            result = subprocess.run(  # noqa: S603
                demucs_cmd,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=sanitized_subprocess_env(),
                timeout=DEFAULT_AI_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            raise ProcessingError(
                " ".join(demucs_cmd), -1, "", reason=f"Demucs command timed out after {DEFAULT_AI_TIMEOUT}s"
            ) from None
        if result.returncode != 0:
            raise ProcessingError(" ".join(demucs_cmd), result.returncode, result.stderr)

        staged_model_dir = Path(stage_dir) / model / audio_name
        staged_files: dict[str, Path] = {}
        for stem in stems:
            stem_file = staged_model_dir / f"{stem}.wav"
            if stem_file.is_file():
                staged_files[stem] = stem_file
        missing = [stem for stem in stems if stem not in staged_files]
        if missing:
            # A partial dict read as success left downstream mixes pointing at files that do not exist.
            raise ProcessingError(
                " ".join(demucs_cmd),
                result.returncode,
                result.stderr,
                reason="Demucs finished without writing every requested stem file",
            )

        result_paths: dict[str, str] = {}
        for stem in stems:
            dest = destinations[stem]
            with (
                _atomic_output(str(dest)) as atomic_stage,
                open(staged_files[stem], "rb") as reader,
                _open_staged_writer(atomic_stage) as writer,
            ):
                shutil.copyfileobj(reader, writer)
            result_paths[stem] = str(dest)

    return result_paths


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
    if is_offline_mode():
        raise MCPVideoError(
            "Automatic Demucs weight loading is disabled offline. Use existing local stem WAVs.",
            error_type="offline_error",
            code="offline_network_blocked",
        )
    _validate_input_path(video)

    # Check for demucs availability
    try:
        importlib.import_module("demucs.separate")
    except ImportError:
        hint = pip_install_hint("stems")
        raise MCPVideoError(
            f"Demucs not installed. Install with: {hint}",
            error_type="dependency_error",
            code="missing_demucs",
            suggested_action={
                "auto_fix": False,
                "description": f"Run: {hint} to enable stem separation",
            },
        ) from None

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)
    _validate_stem_duration(str(video_path))

    # Default stems if not provided
    stems = stems or ["vocals", "drums", "bass", "other"]

    # Validate output directory
    resolved_dir = validate_artifact_location(output_dir, "Output directory")
    if os.path.lexists(resolved_dir) and not os.path.isdir(resolved_dir):
        raise MCPVideoError(
            "Output directory target is not a directory",
            error_type="validation_error",
            code="unsafe_path",
        )
    output_path = Path(output_dir)

    # Step 1: Extract audio from video to temp WAV file
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        audio_path = tmp.name

    try:
        _extract_stem_audio(video_path, audio_path)
        return _run_demucs_separation(audio_path, output_path, model, stems)

    finally:
        # Clean up temp audio file
        Path(audio_path).unlink(missing_ok=True)
