"""Deterministic tiled motion-strip rendering over sampled frame artifacts."""

from __future__ import annotations

from kinocut.aivideo.inspection.manifest import (
    ArtifactRef,
    MotionStripArtifactRef,
    TimestampedArtifactRef,
)
from kinocut.defaults import (
    DEFAULT_INSPECTION_IMAGE_QUALITY,
    DEFAULT_MOTION_STRIP_CELL_HEIGHT,
    DEFAULT_MOTION_STRIP_CELL_WIDTH,
)
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffmpeg_bytes
from kinocut.projectstore import Project, store
from kinocut.projectstore.artifacts import install_bytes


def _filter(frame_count: int) -> str:
    parts = [
        (
            f"[{index}:v]scale={DEFAULT_MOTION_STRIP_CELL_WIDTH}:"
            f"{DEFAULT_MOTION_STRIP_CELL_HEIGHT}:force_original_aspect_ratio=decrease,"
            f"pad={DEFAULT_MOTION_STRIP_CELL_WIDTH}:{DEFAULT_MOTION_STRIP_CELL_HEIGHT}:"
            f"(ow-iw)/2:(oh-ih)/2[s{index}]"
        )
        for index in range(frame_count)
    ]
    labels = "".join(f"[s{index}]" for index in range(frame_count))
    if frame_count == 1:
        parts.append("[s0]null[strip]")
    else:
        parts.append(f"{labels}hstack=inputs={frame_count}[strip]")
    return ";".join(parts)


def _render(project: Project, frames: tuple[TimestampedArtifactRef, ...]) -> bytes:
    inputs: list[str] = []
    for frame in frames:
        source = store.safe_target(project, frame.artifact.location)
        if not source.is_file():
            raise MCPVideoError(
                "motion strip references a missing sampled frame",
                error_type="store_error",
                code="sampled_frame_missing",
            )
        inputs.extend(["-i", str(source)])
    return _run_ffmpeg_bytes(
        [
            *inputs,
            "-filter_complex",
            _filter(len(frames)),
            "-map",
            "[strip]",
            "-frames:v",
            "1",
            "-q:v",
            str(DEFAULT_INSPECTION_IMAGE_QUALITY),
            "-threads",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "pipe:1",
        ]
    )


def build_motion_strip(project: Project, frames: tuple[TimestampedArtifactRef, ...]) -> MotionStripArtifactRef:
    """Tile every sampled frame left-to-right and install the strip canonically."""

    if not frames:
        raise MCPVideoError(
            "motion strip requires at least one sampled frame",
            error_type="validation_error",
            code="motion_strip_empty",
        )
    timestamps = tuple(frame.timestamp for frame in frames)
    if tuple(sorted(set(timestamps))) != timestamps:
        raise MCPVideoError(
            "motion strip samples must be unique and ascending",
            error_type="validation_error",
            code="motion_strip_order",
        )
    rendered = _render(project, frames)
    installed = install_bytes(project, rendered, name="motion_strip.jpg")
    return MotionStripArtifactRef(
        artifact=ArtifactRef(
            artifact_id=installed.artifact_id,
            kind="motion_strip",
            location=installed.location,
        ),
        sample_timestamps=timestamps,
    )
