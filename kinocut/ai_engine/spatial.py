"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import (
    _get_video_duration,
    _run_command,
    _run_ffprobe_json,
    _validate_input_path,
    _validate_output_path,
)
from ..limits import DEFAULT_FFMPEG_TIMEOUT
from ..engine_runtime_utils import _get_audio_stream

logger = logging.getLogger(__name__)


def _require_audio_stream(video: str) -> None:
    data = _run_ffprobe_json(video)
    if _get_audio_stream(data) is None:
        raise MCPVideoError(
            "Input video must contain an audio stream for spatial audio",
            error_type="validation_error",
            code="missing_audio_stream",
        )


def _standard_scene_detect(video: str, threshold: float) -> list[dict]:
    """Standard FFmpeg scene detection."""
    _validate_input_path(video)
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)
    if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(
            f"threshold must be between 0.0 and 1.0, got {threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    cmd = ["ffmpeg", "-i", video, "-filter:v", f"select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    result = _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

    scenes = []
    for line in result.stderr.split("\n"):
        if "pts_time:" in line:
            # Extract timestamp
            match = re.search(r"pts_time:([\d.]+)", line)
            if match:
                scenes.append(
                    {
                        "timestamp": float(match.group(1)),
                        "frame": None,  # Could extract from output
                    }
                )

    return scenes


def audio_spatial(
    video: str,
    output: str,
    positions: list[dict],
    method: str = "hrtf",
) -> str:
    """3D spatial audio positioning.

    Args:
        video: Input video path
        output: Output video path
        positions: List of {time, azimuth, elevation} for audio positioning
        method: Spatialization method (hrtf, vbap, simple)

    Returns:
        Path to output video

    Raises:
        FileNotFoundError: If input video doesn't exist
        RuntimeError: If FFmpeg processing fails
    """
    _validate_input_path(video)

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)

    # Validate positions
    if not positions:
        raise MCPVideoError("At least one position must be provided", error_type="validation_error")

    _require_audio_stream(str(video_path))

    # Validate method
    valid_methods = ("hrtf", "vbap", "simple")
    if method not in valid_methods:
        raise MCPVideoError(f"Method must be one of {valid_methods}, got {method}", error_type="validation_error")

    _validate_output_path(output)
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # All methods currently fall back to simple spatial processing
    # HRTF and VBAP require specialized filters not yet implemented
    return _apply_simple_spatial(video, output, positions)


def _azimuth_to_pan(azimuth: float) -> float:
    """Convert azimuth angle to pan value.

    Args:
        azimuth: Angle in degrees (-90 = left, 0 = center, 90 = right)

    Returns:
        Pan value (-1.0 = left, 0 = center, 1.0 = right)
    """
    # -90 (left) -> -1.0, 0 (center) -> 0, 90 (right) -> 1.0
    return max(-1.0, min(1.0, azimuth / 90.0))


def _elevation_to_volume(elevation: float) -> float:
    """Convert elevation to volume multiplier.

    Args:
        elevation: Angle in degrees (0 = level, 90 = directly above)

    Returns:
        Volume multiplier (1.0 = level, ~0.7 = directly above)
    """
    # Higher elevation = slightly quieter (distance effect)
    # 0 (level) -> 1.0, 90 (above) -> 0.7
    return max(0.0, min(2.0, 1.0 - (elevation / 90.0) * 0.3))


def _apply_simple_spatial(
    video: str,
    output: str,
    positions: list[dict],
) -> str:
    """Apply simple spatial audio using pan and volume filters.

    Uses FFmpeg's pan filter for stereo positioning and volume for elevation.
    Creates animated audio positioning based on keyframes.

    Note: The 'pan' filter doesn't support timeline (enable) option, so we
    use volume filter with enable for volume changes, and apply a static
    pan for the primary position or use asplit/aselect for complex routing.

    For simplicity, this implementation uses volume for elevation simulation
    and applies a balanced pan for overall stereo field positioning.

    Args:
        video: Input video path
        output: Output video path
        positions: List of {time, azimuth, elevation} keyframes

    Returns:
        Path to output video
    """
    if not positions:
        raise MCPVideoError("At least one position must be provided", error_type="validation_error")

    # Sort positions by time
    sorted_positions = sorted(positions, key=lambda p: p.get("time", 0))

    # Get video duration for final position hold
    try:
        duration = _get_video_duration(video)
    except ProcessingError:
        duration = sorted_positions[-1].get("time", 5) + 1

    # For multi-keyframe spatial audio with pan, we need to use a different approach
    # since pan doesn't support timeline enable. We'll segment the audio and apply
    # different pan settings to each segment, then concatenate.

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        segment_files = []

        # Process each position segment
        for i, pos in enumerate(sorted_positions):
            time_start = pos.get("time", 0)
            azimuth = pos.get("azimuth", 0)
            elevation = pos.get("elevation", 0)

            # Determine segment duration
            if i < len(sorted_positions) - 1:
                segment_duration = sorted_positions[i + 1].get("time", duration) - time_start
            else:
                segment_duration = duration - time_start

            if segment_duration <= 0:
                continue

            # Convert to pan and volume values
            pan_value = _azimuth_to_pan(azimuth)
            volume_value = _elevation_to_volume(elevation)

            # Calculate channel gains for pan
            left_gain = max(0.0, min(1.0, 0.5 - pan_value * 0.5))
            right_gain = max(0.0, min(1.0, 0.5 + pan_value * 0.5))

            # Output segment file
            segment_file = tmpdir_path / f"segment_{i:04d}.mp4"
            segment_files.append(segment_file)

            # Build FFmpeg command for this segment
            # Extract segment, apply pan and volume
            filter_complex = (
                f"[0:a]volume={volume_value},"
                f"pan=stereo|c0={left_gain:.3f}*c0+{left_gain:.3f}*c1|"
                f"c1={right_gain:.3f}*c0+{right_gain:.3f}*c1[aout]"
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-ss",
                str(time_start),
                "-t",
                str(segment_duration),
                "-i",
                video,
                "-filter_complex",
                filter_complex,
                "-map",
                "0:v",  # Copy video stream
                "-map",
                "[aout]",  # Use processed audio
                "-c:v",
                "copy",  # Copy video without re-encoding
                "-c:a",
                "aac",  # Re-encode audio
                "-b:a",
                "192k",
                str(segment_file),
            ]

            _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

        # Concatenate all segments
        if len(segment_files) == 1:
            # Single segment - just copy
            shutil.copy2(str(segment_files[0]), output)
        else:
            # Multiple segments - use concat demuxer
            concat_list = tmpdir_path / "concat_list.txt"
            with open(concat_list, "w") as f:
                for seg_file in segment_files:
                    # Escape single quotes in path
                    escaped_path = str(seg_file).replace("'", "'\\''")
                    f.write(f"file '{escaped_path}'\n")

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_list),
                "-c",
                "copy",
                output,
            ]

            _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

    return output
