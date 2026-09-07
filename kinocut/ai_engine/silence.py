"""AI-powered video processing using machine learning models.

Optional dependencies:
    - openai-whisper: For speech-to-text transcription
    - imagehash: For AI-enhanced scene detection
    - Pillow: For image processing in scene detection
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ..audio_bed_validation import reject_output_alias
from ..defaults import (
    DEFAULT_AUDIO_BITRATE,
    DEFAULT_CRF,
    DEFAULT_FFMPEG_TIMEOUT,
    DEFAULT_PRESET,
    DEFAULT_SILENCE_DURATION_TOLERANCE_SECONDS,
    DEFAULT_SILENCE_MOV_AUDIO_CODEC,
    DEFAULT_SILENCE_MOV_PIXEL_FORMAT,
    DEFAULT_SILENCE_MOV_VIDEO_CODEC,
)
from ..errors import InputFileError, MCPVideoError, ProcessingError
from ..ffmpeg_helpers import (
    _atomic_output,
    _format_ffmpeg_number,
    _run_command,
    _run_ffprobe_json,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)

logger = logging.getLogger(__name__)

_MOV_FAMILY_SUFFIXES = frozenset({".mp4", ".m4v", ".mov"})
_CONTAINER_FORMATS = {
    ".mp4": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".m4v": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".mov": frozenset({"mov", "mp4", "m4a", "3gp", "3g2", "mj2"}),
    ".mkv": frozenset({"matroska"}),
    ".webm": frozenset({"webm"}),
}


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
    video_duration = _sanitize_ffmpeg_number(video_duration, "video_duration")
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

    keep_segments: list[tuple[float, float]] = []
    current_pos = 0.0

    for silence_start, silence_end in silence_regions:
        start = _sanitize_ffmpeg_number(silence_start, "silence_start")
        end = _sanitize_ffmpeg_number(silence_end, "silence_end")
        start = min(video_duration, max(0.0, start))
        end = min(video_duration, max(0.0, end))
        effective_silence_start = min(video_duration, start + keep_margin)
        effective_silence_end = max(0.0, end - keep_margin)

        if effective_silence_start >= effective_silence_end:
            continue

        if current_pos < effective_silence_start:
            keep_segments.append((current_pos, effective_silence_start))

        current_pos = max(current_pos, effective_silence_end)

    # Add remaining content after last silence
    if current_pos < video_duration:
        keep_segments.append((current_pos, video_duration))

    return keep_segments


def _build_silence_filter_graph(segments: list[tuple[float, float]]) -> str:
    """Build matched video/audio trim chains joined by the concat filter."""
    if not segments:
        raise MCPVideoError("No segments to keep", error_type="validation_error", code="invalid_parameter")

    chains: list[str] = []
    concat_inputs: list[str] = []
    for index, (start, end) in enumerate(segments):
        start_text = _format_ffmpeg_number(_sanitize_ffmpeg_number(start, "segment_start"))
        end_text = _format_ffmpeg_number(_sanitize_ffmpeg_number(end, "segment_end"))
        chains.extend(
            (
                f"[0:v:0]trim=start={start_text}:end={end_text},setpts=PTS-STARTPTS[v{index}]",
                f"[0:a:0]atrim=start={start_text}:end={end_text},asetpts=PTS-STARTPTS[a{index}]",
            )
        )
        concat_inputs.append(f"[v{index}][a{index}]")
    chains.append(f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[vout][aout]")
    return ";".join(chains)


def _silence_output_args(output: str) -> list[str]:
    """Return explicit MOV-family codecs; other muxers choose compatible defaults."""
    if Path(output).suffix.lower() not in _MOV_FAMILY_SUFFIXES:
        return []
    return [
        "-c:v",
        DEFAULT_SILENCE_MOV_VIDEO_CODEC,
        "-preset",
        DEFAULT_PRESET,
        "-crf",
        str(DEFAULT_CRF),
        "-pix_fmt",
        DEFAULT_SILENCE_MOV_PIXEL_FORMAT,
        "-c:a",
        DEFAULT_SILENCE_MOV_AUDIO_CODEC,
        "-b:a",
        DEFAULT_AUDIO_BITRATE,
        "-movflags",
        "+faststart",
    ]


def _render_keep_segments(video: str, segments: list[tuple[float, float]], output: str) -> None:
    """Render keep intervals in one frame-accurate audio/video filtergraph."""
    graph = _build_silence_filter_graph(segments)
    _run_command(
        [
            "ffmpeg",
            "-y",
            "-i",
            video,
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            *_silence_output_args(output),
            output,
        ],
        timeout=DEFAULT_FFMPEG_TIMEOUT,
    )


def _processing_failure(reason: str, returncode: int = 0) -> ProcessingError:
    """Create a stable path-free output-validation error."""
    return ProcessingError("silence output validation", returncode, reason)


def _validate_silence_output(output: str, expected_duration: float) -> None:
    """Require a compatible, complete, fully decodable staged artifact."""
    try:
        info = _run_ffprobe_json(output)
    except ProcessingError as exc:
        raise _processing_failure("staged output could not be probed", exc.returncode) from None

    format_info = info.get("format")
    streams = info.get("streams")
    if not isinstance(format_info, dict) or not isinstance(streams, list):
        raise _processing_failure("staged output has incomplete probe metadata")
    format_names = set(str(format_info.get("format_name", "")).split(",")) - {""}
    expected_formats = _CONTAINER_FORMATS.get(Path(output).suffix.lower())
    if not format_names or (expected_formats is not None and not format_names & expected_formats):
        raise _processing_failure("staged output container does not match the requested suffix")

    try:
        duration = _sanitize_ffmpeg_number(format_info.get("duration"), "output_duration")
    except MCPVideoError:
        raise _processing_failure("staged output has no finite duration") from None
    expected_duration = _sanitize_ffmpeg_number(expected_duration, "expected_duration")
    if duration <= 0 or abs(duration - expected_duration) > DEFAULT_SILENCE_DURATION_TOLERANCE_SECONDS:
        raise _processing_failure("staged output duration is outside the accepted tolerance")

    video_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "video"]
    audio_streams = [stream for stream in streams if isinstance(stream, dict) and stream.get("codec_type") == "audio"]
    if len(video_streams) != 1 or len(audio_streams) != 1:
        raise _processing_failure("staged output must contain one video stream and one audio stream")
    if Path(output).suffix.lower() in _MOV_FAMILY_SUFFIXES and (
        video_streams[0].get("codec_name") != "h264" or audio_streams[0].get("codec_name") != "aac"
    ):
        raise _processing_failure("MOV-family output does not use H.264 video and AAC audio")

    try:
        _run_command(
            ["ffmpeg", "-v", "error", "-xerror", "-i", output, "-map", "0", "-f", "null", "-"],
            timeout=DEFAULT_FFMPEG_TIMEOUT,
        )
    except ProcessingError as exc:
        raise _processing_failure("staged output failed full media decode", exc.returncode) from None


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
    validated_video = _validate_input_path(video)

    # Validate input file
    video_path = Path(validated_video)
    if not video_path.exists():
        raise InputFileError(video)
    _validate_output_path(output)
    reject_output_alias(output, (validated_video,))

    # Step 1: Get video duration
    info = _run_ffprobe_json(str(video_path))
    try:
        video_duration = _sanitize_ffmpeg_number(info.get("format", {}).get("duration"), "video_duration")
    except MCPVideoError:
        raise MCPVideoError(
            "Could not determine video duration", error_type="processing_error", code="probe_failed"
        ) from None

    if video_duration <= 0:
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

    if not keep_segments:
        raise MCPVideoError("No segments to keep", error_type="validation_error", code="invalid_parameter")

    expected_duration = sum(end - start for start, end in keep_segments)
    with _atomic_output(output) as staged_output:
        _render_keep_segments(str(video_path), keep_segments, staged_output)
        _validate_silence_output(staged_output, expected_duration)
    return output


# ---------------------------------------------------------------------------
# Audio Stem Separation (Demucs)
# ---------------------------------------------------------------------------
