"""Storyboard extraction operation for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil

from .ffmpeg_helpers import _validate_input_path
from .engine_probe import get_duration
from .paths import _auto_output_dir
from .ffmpeg_helpers import _run_ffmpeg
from .errors import MCPVideoError, ProcessingError
from .models import StoryboardResult


def storyboard(
    input_path: str,
    output_dir: str | None = None,
    frame_count: int = 8,
) -> StoryboardResult:
    """Extract key frames and create a storyboard grid for human review."""
    input_path = _validate_input_path(input_path)
    if frame_count < 1:
        raise MCPVideoError("frame_count must be at least 1", code="invalid_frame_count")
    dur = get_duration(input_path)

    out_dir = output_dir or _auto_output_dir(input_path, "storyboard")
    os.makedirs(out_dir, exist_ok=True)

    frame_paths: list[str] = []
    interval = dur / (frame_count + 1)

    for i in range(frame_count):
        ts = interval * (i + 1)
        frame_name = f"frame_{i + 1:02d}_{ts:.1f}s.jpg"
        frame_path = os.path.join(out_dir, frame_name)

        _run_ffmpeg(
            [
                "-ss",
                str(ts),
                "-i",
                input_path,
                "-vframes",
                "1",
                "-q:v",
                "2",
                "-y",
                frame_path,
            ]
        )
        frame_paths.append(frame_path)

    # Create storyboard grid using FFmpeg
    grid_path = os.path.join(out_dir, "storyboard_grid.jpg")
    if len(frame_paths) >= 2:
        # Create a grid of frames
        cols = min(4, len(frame_paths))
        rows = (len(frame_paths) + cols - 1) // cols

        # Use FFmpeg to tile the images
        # Build a complex filter for the grid
        inputs = []
        for fp in frame_paths:
            inputs.extend(["-i", fp])

        # Normalize all frames to same size
        filter_parts = []
        for i, _fp in enumerate(frame_paths):
            filter_parts.append(
                f"[{i}:v]scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2[s{i}]"
            )

        # Stack horizontally first, then vertically
        # Row 0: [s0][s1][s2][s3]hstack=inputs=4[r0]
        # Row 1: [s4][s5][s6][s7]hstack=inputs=4[r1]
        # Final: [r0][r1]vstack=inputs=2[vout]

        row_labels: list[str] = []
        for row in range(rows):
            start = row * cols
            end = min(start + cols, len(frame_paths))
            actual_cols = end - start
            input_labels = "".join(f"[s{j}]" for j in range(start, end))
            row_label = f"r{row}"
            filter_parts.append(f"{input_labels}hstack=inputs={actual_cols}[{row_label}]")
            row_labels.append(f"[{row_label}]")

        vstack_inputs = "".join(row_labels)
        filter_parts.append(f"{vstack_inputs}vstack=inputs={rows}[vout]")

        filter_str = ";".join(filter_parts)

        try:
            _run_ffmpeg([*inputs, "-filter_complex", filter_str, "-map", "[vout]", "-q:v", "2", "-y", grid_path])
        except ProcessingError:
            # Grid creation failed — frames are still useful individually
            grid_path = None
    elif len(frame_paths) == 1:
        shutil.copy2(frame_paths[0], grid_path)
    else:
        grid_path = None

    return StoryboardResult(
        frames=frame_paths,
        grid=grid_path,
        count=len(frame_paths),
    )
