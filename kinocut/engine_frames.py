"""Frame sequence export operations for the FFmpeg engine."""

from __future__ import annotations

import os
import shutil
import tempfile

from .engine_probe import probe
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _atomic_output,
    _open_staged_writer,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .models import ImageSequenceResult
from .paths import _auto_output_dir
from .publication import validate_artifact_location
from .validation_errors import rejected_value


def export_frames(
    input_path: str,
    output_dir: str | None = None,
    fps: float = 1.0,
    format: str = "jpg",
) -> ImageSequenceResult:
    """Export frames from a video as individual images.

    Args:
        input_path: Path to the input video.
        output_dir: Directory for extracted frames.
        fps: Frames per second to extract (1.0 = 1 frame per second).
        format: Output image format (jpg, png).
    """
    input_path = _validate_input_path(input_path)
    fps = _sanitize_ffmpeg_number(fps, "fps")
    if fps <= 0:
        # Some FFmpeg builds (5.x) silently accept fps=0 and write nothing.
        raise MCPVideoError(
            f"fps must be greater than 0, got {fps}",
            error_type="validation_error",
            code="invalid_parameter",
        )
    if format == "mjpeg":
        format = "jpg"
    if format not in ("jpg", "png"):
        raise MCPVideoError(
            f"Invalid format '{rejected_value(format)}': must be 'jpg', 'mjpeg' or 'png'",
            error_type="validation_error",
            code="invalid_format",
        )
    probe(input_path)

    out_dir = output_dir or _auto_output_dir(input_path, "frames")
    resolved_dir = validate_artifact_location(out_dir, "Output directory")
    if os.path.lexists(resolved_dir) and not os.path.isdir(resolved_dir):
        raise MCPVideoError(
            "Output directory target is not a directory",
            error_type="validation_error",
            code="unsafe_path",
        )

    ext = format if format.startswith(".") else f".{format}"
    frame_paths: list[str] = []
    with tempfile.TemporaryDirectory(prefix="kinocut-frames-") as stage_dir:
        pattern = os.path.join(stage_dir, f"frame_%04d{ext}")
        _run_ffmpeg(
            [
                "-i",
                input_path,
                "-vf",
                f"fps={fps}",
                "-q:v",
                "2",
                "-y",
                pattern,
            ]
        )

        staged_names = sorted(f for f in os.listdir(stage_dir) if f.startswith("frame_") and f.endswith(ext))
        destinations = [os.path.join(out_dir, name) for name in staged_names]
        # Validate every destination up front so default overwrite=False never
        # partially writes frames before failing on a pre-existing file.
        for dest in destinations:
            _validate_output_path(dest)

        for name, dest in zip(staged_names, destinations, strict=True):
            src = os.path.join(stage_dir, name)
            with _atomic_output(dest) as staged, open(src, "rb") as reader, _open_staged_writer(staged) as writer:
                shutil.copyfileobj(reader, writer)
            frame_paths.append(dest)

    return ImageSequenceResult(
        frame_paths=frame_paths,
        frame_count=len(frame_paths),
        fps=fps,
    )
