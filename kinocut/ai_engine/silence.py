"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from ..errors import InputFileError, MCPVideoError
from ..ffmpeg_helpers import (
    _run_command,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from ..limits import DEFAULT_FFMPEG_TIMEOUT

logger = logging.getLogger(__name__)


def _detect_silence_regions(
    video: str,
    silence_threshold: float,
    min_silence_duration: float,
) -> list[tuple[float, float]]:
    """Detect silent regions in video using silencedetect filter.

    Returns:
        List of (start, end) tuples for silent regions.
    """
    silence_threshold = _sanitize_ffmpeg_number(silence_threshold, "silence_threshold")
    min_silence_duration = _sanitize_ffmpeg_number(min_silence_duration, "min_silence_duration")
    if silence_threshold > 0:
        raise MCPVideoError(
            f"silence_threshold must be <= 0 dB, got {silence_threshold}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if min_silence_duration <= 0:
        raise MCPVideoError(
            f"min_silence_duration must be > 0, got {min_silence_duration}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    # Run silencedetect filter
    cmd = [
        "ffmpeg",
        "-i",
        video,
        "-af",
        f"silencedetect=noise={silence_threshold}dB:d={min_silence_duration}",
        "-f",
        "null",
        "-",
    ]

    result = _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)

    # Parse silence_start and silence_end from stderr
    silence_regions = []
    silence_starts = re.findall(r"silence_start: ([\d.]+)", result.stderr)
    silence_ends = re.findall(r"silence_end: ([\d.]+)", result.stderr)

    # Pair up starts and ends
    for i, start in enumerate(silence_starts):
        if i < len(silence_ends):
            silence_regions.append((float(start), float(silence_ends[i])))
        else:
            # Silence extends to end of video
            # Get video duration
            info = _run_ffprobe_json(video)
            duration = float(info.get("format", {}).get("duration", 0))
            silence_regions.append((float(start), duration))

    return silence_regions


def _build_keep_segments(
    silence_regions: list[tuple[float, float]],
    video_duration: float,
    keep_margin: float,
) -> list[tuple[float, float]]:
    """Build segments to keep by inverting silence regions.

    Args:
        silence_regions: List of (start, end) tuples for silent regions
        video_duration: Total video duration
        keep_margin: Margin to keep around removed silence

    Returns:
        List of (start, end) tuples for segments to keep.
    """
    keep_margin = _sanitize_ffmpeg_number(keep_margin, "keep_margin")
    if keep_margin < 0:
        raise MCPVideoError(
            f"keep_margin must be >= 0, got {keep_margin}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if not silence_regions:
        # No silence detected, keep entire video
        return [(0, video_duration)]

    keep_segments = []
    current_pos = 0.0

    for silence_start, silence_end in silence_regions:
        # Add margin to silence boundaries
        effective_silence_start = max(0, silence_start + keep_margin)
        effective_silence_end = max(effective_silence_start, silence_end - keep_margin)

        # If silence region is too small after margins, skip it
        if effective_silence_start >= effective_silence_end:
            current_pos = silence_end
            continue

        # If there's content before the silence, keep it
        if current_pos < effective_silence_start:
            keep_segments.append((current_pos, effective_silence_start))

        current_pos = silence_end

    # Add remaining content after last silence
    if current_pos < video_duration:
        keep_segments.append((current_pos, video_duration))

    return keep_segments


def _concat_segments(
    video: str,
    segments: list[tuple[float, float]],
    output: str,
) -> str:
    """Concatenate video segments using FFmpeg.

    Uses segment extraction followed by concat demuxer.
    """
    if not segments:
        raise MCPVideoError("No segments to keep", error_type="validation_error", code="invalid_parameter")

    if len(segments) == 1:
        # Single segment - just trim
        start, end = segments[0]
        duration = end - start
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-ss",
            str(start),
            "-t",
            str(duration),
            "-c",
            "copy",
            output,
        ]
        _run_command(cmd, timeout=DEFAULT_FFMPEG_TIMEOUT)
        return output

    # Multiple segments - extract each and concatenate
    segment_files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, (start, end) in enumerate(segments):
            segment_file = Path(tmpdir) / f"segment_{i:04d}.mp4"
            duration = end - start

            _run_command(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    video,
                    "-ss",
                    str(start),
                    "-t",
                    str(duration),
                    "-c",
                    "copy",
                    str(segment_file),
                ],
                timeout=DEFAULT_FFMPEG_TIMEOUT,
            )

            segment_files.append(str(segment_file))

        # Create concat list file
        concat_list = Path(tmpdir) / "concat_list.txt"
        with open(concat_list, "w") as f:
            for seg_file in segment_files:
                # Escape single quotes in file path
                escaped = seg_file.replace("'", "'\\''")
                f.write(f"file '{escaped}'\n")

        # Concatenate using concat demuxer
        _run_command(
            [
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
            ],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )

    return output


def ai_remove_silence(
    video: str,
    output: str,
    silence_threshold: float = -50,  # dB
    min_silence_duration: float = 0.5,
    keep_margin: float = 0.1,
) -> str:
    """Auto-remove silent sections from video.

    Uses FFmpeg's silencedetect filter to identify silent regions,
    then removes them while keeping specified margins.

    Args:
        video: Input video path
        output: Output video path
        silence_threshold: Silence threshold in dB (default -50)
        min_silence_duration: Minimum silence to remove in seconds
        keep_margin: Keep this much margin around removed silence

    Returns:
        Path to output video
    """
    _validate_input_path(video)

    # Validate input file
    video_path = Path(video)
    if not video_path.exists():
        raise InputFileError(video)
    _validate_output_path(output)

    # Step 1: Get video duration
    info = _run_ffprobe_json(str(video_path))
    video_duration = float(info.get("format", {}).get("duration", 0))

    if video_duration == 0:
        raise MCPVideoError("Could not determine video duration", error_type="processing_error", code="probe_failed")

    # Step 2: Detect silent sections
    silence_regions = _detect_silence_regions(
        str(video_path),
        silence_threshold=silence_threshold,
        min_silence_duration=min_silence_duration,
    )

    # Step 3: Build segments to keep (invert silence regions)
    keep_segments = _build_keep_segments(
        silence_regions,
        video_duration,
        keep_margin=keep_margin,
    )

    # Step 4: Concatenate keep segments
    return _concat_segments(str(video_path), keep_segments, output)


# ---------------------------------------------------------------------------
# Audio Stem Separation (Demucs)
# ---------------------------------------------------------------------------
