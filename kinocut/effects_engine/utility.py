"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any

from ..errors import MCPVideoError, ProcessingError
from ..ffmpeg_helpers import _run_command, _run_ffprobe_json, _validate_input_path
from ..limits import DEFAULT_FFMPEG_TIMEOUT

logger = logging.getLogger(__name__)


def _rgb_to_hex(rgb: bytes) -> str:
    """Convert three RGB bytes to a hex color string."""
    return f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"


def _extract_representative_colors(video: str, duration: float, max_colors: int = 3) -> list[str]:
    """Extract simple representative frame colors without optional image dependencies."""
    if max_colors < 1:
        return []

    sample_times = [0.0]
    if duration > 0:
        sample_times = [max(0.0, duration * ratio) for ratio in (0.1, 0.5, 0.9)]

    colors: list[str] = []
    for timestamp in sample_times:
        cmd = [
            "ffmpeg",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            video,
            "-frames:v",
            "1",
            "-vf",
            "scale=1:1",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=DEFAULT_FFMPEG_TIMEOUT)  # noqa: S603
        except subprocess.TimeoutExpired as exc:
            raise ProcessingError(
                " ".join(cmd), -1, f"FFmpeg command timed out after {DEFAULT_FFMPEG_TIMEOUT}s"
            ) from exc
        if result.returncode != 0:
            raise ProcessingError(" ".join(cmd), result.returncode, result.stderr.decode(errors="replace"))
        if len(result.stdout) < 3:
            raise ProcessingError(" ".join(cmd), result.returncode, "FFmpeg returned no RGB frame data")

        color = _rgb_to_hex(result.stdout[:3])
        if color not in colors:
            colors.append(color)
        if len(colors) >= max_colors:
            break

    return colors


def video_info_detailed(video: str) -> dict[str, Any]:
    """Get extended video metadata.

    Args:
        video: Video file path

    Returns:
        Dict with duration, fps, resolution, bitrate, has_audio,
        scene_changes, dominant_colors
    """
    video = _validate_input_path(video)

    # Get basic info through the shared ffprobe helper (resolved binary path)
    data = _run_ffprobe_json(video)

    # Extract video stream info
    video_stream = None
    audio_stream = None

    for stream in data.get("streams", []):
        if stream["codec_type"] == "video":
            video_stream = stream
        elif stream["codec_type"] == "audio":
            audio_stream = stream

    if not video_stream:
        raise MCPVideoError("No video stream found", error_type="processing_error", code="no_video_stream")

    # Calculate duration
    duration = float(video_stream.get("duration", 0) or data.get("format", {}).get("duration", 0))

    # Calculate FPS
    fps_str = video_stream.get("r_frame_rate", "30/1")
    if "/" in fps_str:
        num, den = map(int, fps_str.split("/"))
        fps = num / den if den else 30
    else:
        fps = float(fps_str)

    resolution = [video_stream.get("width", 0), video_stream.get("height", 0)]
    bitrate = int(data.get("format", {}).get("bit_rate", 0))

    # Try to detect scene changes
    scene_changes = []
    try:
        scene_cmd = [
            "ffmpeg",
            "-i",
            video,
            "-filter:v",
            "select='gt(scene,0.3)',showinfo",
            "-f",
            "null",
            "-",
        ]
        scene_result = subprocess.run(scene_cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
        # Parse scene change timestamps from stderr
        for line in scene_result.stderr.split("\n"):
            if "pts_time:" in line:
                # Extract timestamp
                parts = line.split("pts_time:")
                if len(parts) > 1:
                    try:
                        ts = float(parts[1].split()[0])
                        scene_changes.append(ts)
                    except (ValueError, IndexError):
                        pass
    except Exception as e:
        logger = logging.getLogger(__name__)
        logger.warning("Scene detection failed (optional): %s", e)

    dominant_colors = _extract_representative_colors(video, duration)

    return {
        "duration": duration,
        "fps": fps,
        "resolution": resolution,
        "bitrate": bitrate,
        "has_audio": audio_stream is not None,
        "scene_changes": scene_changes[:10],  # Limit to first 10
        "dominant_colors": dominant_colors,
    }


def auto_chapters(
    video: str,
    threshold: float = 0.3,
) -> list[tuple[float, str]]:
    """Auto-detect scene changes and create chapters.

    Args:
        video: Video file path
        threshold: Scene change detection threshold

    Returns:
        List of (timestamp, description) tuples

    Raises:
        MCPVideoError: If *threshold* is not a number in [0.0, 1.0].
    """
    video = _validate_input_path(video)

    if not isinstance(threshold, (int, float)) or not (0.0 <= threshold <= 1.0):
        raise MCPVideoError(f"threshold must be a number between 0.0 and 1.0, got {threshold!r}")

    chapters = []

    cmd = [
        "ffmpeg",
        "-i",
        video,
        "-filter:v",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]

    result = _run_command(cmd, timeout=60)

    chapter_num = 1
    for line in result.stderr.split("\n"):
        if "pts_time:" in line:
            parts = line.split("pts_time:")
            if len(parts) > 1:
                try:
                    ts = float(parts[1].split()[0])
                    chapters.append((ts, f"Chapter {chapter_num}"))
                    chapter_num += 1
                except (ValueError, IndexError):
                    pass

    return chapters
