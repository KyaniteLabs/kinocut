"""Storyboard extraction operation for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .engine_probe import get_duration
from .errors import MCPVideoError, ProcessingError
from .ffmpeg_helpers import (
    _atomic_output,
    _open_staged_writer,
    _run_ffmpeg,
    _validate_input_path,
    _validate_output_path,
)
from .models import StoryboardResult
from .paths import _auto_output_dir
from .publication import validate_artifact_location


def _create_storyboard_grid(frame_paths: list[str], out_dir: str) -> str | None:
    """Create a storyboard grid image from individual frames."""
    grid_path = os.path.join(out_dir, "storyboard_grid.jpg")
    if len(frame_paths) >= 2:
        cols = min(4, len(frame_paths))
        rows = (len(frame_paths) + cols - 1) // cols

        inputs: list[str] = []
        for fp in frame_paths:
            inputs.extend(["-i", fp])

        filter_parts: list[str] = []
        for i, _fp in enumerate(frame_paths):
            filter_parts.append(
                f"[{i}:v]scale=480:270:force_original_aspect_ratio=decrease,"
                f"pad=480:270:(ow-iw)/2:(oh-ih)/2,setsar=1[s{i}]"
            )

        # Pad any ragged last row with black 480x270 filler tiles so every row
        # has identical width and hstack/vstack never receive unary inputs.
        pad_count = rows * cols - len(frame_paths)
        for p in range(pad_count):
            filter_parts.append(f"color=c=black:s=480x270:r=1:d=1,trim=end_frame=1,setsar=1[pad{p}]")

        pad_idx = 0
        row_labels: list[str] = []
        for row in range(rows):
            start = row * cols
            end = min(start + cols, len(frame_paths))
            cells = [f"[s{j}]" for j in range(start, end)]
            while len(cells) < cols:
                cells.append(f"[pad{pad_idx}]")
                pad_idx += 1
            row_label = f"r{row}"
            filter_parts.append(f"{''.join(cells)}hstack=inputs={cols}[{row_label}]")
            row_labels.append(f"[{row_label}]")

        if rows == 1:
            out_label = row_labels[0]
        else:
            filter_parts.append(f"{''.join(row_labels)}vstack=inputs={rows}[vout]")
            out_label = "[vout]"

        filter_str = ";".join(filter_parts)

        try:
            _run_ffmpeg(
                [
                    *inputs,
                    "-filter_complex",
                    filter_str,
                    "-map",
                    out_label,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    "-y",
                    grid_path,
                ]
            )
        except ProcessingError:
            # Grid creation failed — frames are still useful individually
            grid_path = None
    elif len(frame_paths) == 1:
        shutil.copy2(frame_paths[0], grid_path)
    else:
        grid_path = None
    return grid_path


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
    resolved_dir = validate_artifact_location(out_dir, "Output directory")
    if os.path.lexists(resolved_dir) and not os.path.isdir(resolved_dir):
        raise MCPVideoError(
            "Output directory target is not a directory",
            error_type="validation_error",
            code="unsafe_path",
        )

    interval = dur / (frame_count + 1)

    frame_paths: list[str] = []
    grid_path: str | None = None
    with tempfile.TemporaryDirectory(prefix="kinocut-storyboard-") as stage_dir:
        pattern = os.path.join(stage_dir, "sb_frame_%03d.jpg")
        _run_ffmpeg(
            [
                "-ss",
                f"{interval:.3f}",
                "-i",
                input_path,
                "-vf",
                f"fps={1.0 / interval:.6f}",
                "-vframes",
                str(frame_count),
                "-q:v",
                "2",
                "-y",
                pattern,
            ]
        )

        staged_frames: list[tuple[str, str]] = []
        for i, tmp_frame in enumerate(sorted(Path(stage_dir).glob("sb_frame_*.jpg"))):
            ts = interval * (i + 1)
            final_name = f"frame_{i + 1:02d}_{ts:.1f}s.jpg"
            staged_frames.append((str(tmp_frame), os.path.join(out_dir, final_name)))

        staged_grid = _create_storyboard_grid([src for src, _ in staged_frames], stage_dir)
        final_grid = os.path.join(out_dir, "storyboard_grid.jpg") if staged_grid else None

        # Pre-validate all final destinations before publishing anything.
        for _, dest in staged_frames:
            _validate_output_path(dest)
        if final_grid is not None:
            _validate_output_path(final_grid)

        for src, dest in staged_frames:
            with _atomic_output(dest) as staged, open(src, "rb") as reader, _open_staged_writer(staged) as writer:
                shutil.copyfileobj(reader, writer)
            frame_paths.append(dest)

        if staged_grid is not None and final_grid is not None:
            with (
                _atomic_output(final_grid) as staged,
                open(staged_grid, "rb") as reader,
                _open_staged_writer(staged) as writer,
            ):
                shutil.copyfileobj(reader, writer)
            grid_path = final_grid

    return StoryboardResult(
        frames=frame_paths,
        grid=grid_path,
        count=len(frame_paths),
    )
