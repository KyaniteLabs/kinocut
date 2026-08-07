"""Frame-accurate seeking helpers (TE.9)."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError


def frame_to_timestamp(frame: int, fps: float) -> dict[str, Any]:
    if frame < 0:
        raise MCPVideoError("frame must be >= 0", error_type="validation_error", code="bad_frame")
    if fps <= 0:
        raise MCPVideoError("fps must be > 0", error_type="validation_error", code="bad_fps")
    seconds = frame / fps
    return {
        "artifact_kind": "seek_point",
        "frame": frame,
        "fps": fps,
        "seconds": seconds,
        "ffmpeg_ss": f"{seconds:.6f}",
        "notes": "Use -ss after -i for frame-accurate decode path when needed.",
    }


def timestamp_to_frame(seconds: float, fps: float) -> dict[str, Any]:
    if seconds < 0:
        raise MCPVideoError("seconds must be >= 0", error_type="validation_error", code="bad_seconds")
    if fps <= 0:
        raise MCPVideoError("fps must be > 0", error_type="validation_error", code="bad_fps")
    frame = round(seconds * fps)  # int via round for half-up on py3
    return frame_to_timestamp(frame, fps)
