"""Video effects and filters engine.

Visual effects using FFmpeg filters and PIL for custom processing.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _run_command, _escape_ffmpeg_filter_value

logger = logging.getLogger(__name__)

VALID_MOGRAPH_STYLES = {"bar", "circle", "dots"}


def _validate_timing(duration: float, fps: int) -> None:
    if duration <= 0:
        raise MCPVideoError("duration must be positive", error_type="validation_error", code="invalid_parameter")
    if fps <= 0:
        raise MCPVideoError("fps must be positive", error_type="validation_error", code="invalid_parameter")


def mograph_count(
    start: int,
    end: int,
    duration: float,
    output: str,
    style: dict[str, Any] | None = None,
    fps: int = 30,
) -> str:
    """Generate animated number counter video.

    Args:
        start: Starting number
        end: Ending number
        duration: Animation duration in seconds
        output: Output video path
        style: Style dict with font, size, color, glow
        fps: Frame rate

    Returns:
        Path to output video
    """
    _validate_timing(duration, fps)

    style = style or {}
    font = style.get("font", "Arial")
    size = style.get("size", 160)
    color = style.get("color", "white")
    glow = style.get("glow", False)

    # Create temp directory for frames
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        total_frames = int(duration * fps)

        # Generate frames
        for frame in range(total_frames):
            progress = frame / total_frames
            current_value = int(start + (end - start) * progress)

            # Use FFmpeg to generate frame
            frame_file = tmp_path / f"frame_{frame:05d}.png"

            safe_font = _escape_ffmpeg_filter_value(font)
            safe_color = _escape_ffmpeg_filter_value(color)
            text_filter = (
                f"drawtext=text='{current_value}':font={safe_font}:"
                f"fontsize={size}:fontcolor={safe_color}:"
                f"x=(w-text_w)/2:y=(h-text_h)/2"
            )

            if glow:
                text_filter += f":box=1:boxcolor={safe_color}@0.3:boxborderw=10"

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1920x1080:d=1",
                "-vf",
                text_filter,
                "-vframes",
                "1",
                str(frame_file),
            ]

            _run_command(cmd)

        # Combine frames into video
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(tmp_path / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            output,
        ]

        _run_command(cmd)

    return output


def mograph_progress(
    duration: float,
    output: str,
    style: str = "bar",
    color: str = "#CCFF00",
    track_color: str = "#333333",
    fps: int = 30,
) -> str:
    """Generate progress bar / loading animation.

    Args:
        duration: Animation duration in seconds
        output: Output video path
        style: "bar", "circle", or "dots"
        color: Progress color
        track_color: Background track color
        fps: Frame rate

    Returns:
        Path to output video
    """
    _validate_timing(duration, fps)
    if style not in VALID_MOGRAPH_STYLES:
        raise MCPVideoError(
            f"style must be one of {sorted(VALID_MOGRAPH_STYLES)}, got {style}",
            error_type="validation_error",
            code="invalid_parameter",
        )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        total_frames = int(duration * fps)

        for frame in range(total_frames):
            progress = frame / total_frames
            frame_file = tmp_path / f"frame_{frame:05d}.png"

            safe_color = _escape_ffmpeg_filter_value(color)
            safe_track_color = _escape_ffmpeg_filter_value(track_color)

            if style == "bar":
                # Progress bar
                bar_width = int(800 * progress)
                # Draw track
                filter_chain = (
                    f"drawbox=x=560:y=540:w=800:h=20:color={safe_track_color}:t=fill,"
                    f"drawbox=x=560:y=540:w={bar_width}:h=20:color={safe_color}:t=fill"
                )
            elif style == "circle":
                # Circular progress (simplified as arc)
                filter_chain = (
                    f"drawbox=x=860:y=440:w=200:h=200:color={safe_track_color}:t=fill,"
                    f"drawbox=x=860:y=440:w={int(200 * progress)}:h=200:color={safe_color}:t=fill"
                )
            else:
                # Dots
                num_dots = 5
                active_dots = int(num_dots * progress)
                filter_chain = ""
                for i in range(num_dots):
                    x = 760 + i * 80
                    dot_color = safe_color if i < active_dots else safe_track_color
                    filter_chain += f"drawbox=x={x}:y=540:w=20:h=20:color={dot_color}:t=fill,"
                filter_chain = filter_chain.rstrip(",")

            cmd = [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=1920x1080:d=1",
                "-vf",
                filter_chain,
                "-vframes",
                "1",
                str(frame_file),
            ]

            _run_command(cmd)

        # Combine frames
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(tmp_path / "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "23",
            output,
        ]

        _run_command(cmd)

    return output


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------
