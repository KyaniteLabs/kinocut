"""Detect stitched equirect 360 sources. Reject Insta360 .insv originals."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffprobe_json, _validate_input_path
from kinocut.validation import SPHERE_EQUIRECT_ASPECT, SPHERE_EQUIRECT_ASPECT_TOLERANCE


def probe_360_source(path: str) -> dict[str, Any]:
    """Return source facts if ``path`` is a stitched equirect video."""
    if str(path).lower().endswith(".insv"):
        raise MCPVideoError(
            "Insta360 .insv originals cannot be stitched here. Export a "
            "stitched 360 MP4 from Insta360 Studio or the Insta360 app first.",
            error_type="validation_error",
            code="not_insv_export",
            suggested_action={
                "auto_fix": False,
                "description": "Export a stitched equirect MP4, then retry.",
            },
        )
    resolved = _validate_input_path(path)
    width, height, duration, spherical = _probe_geometry(resolved)
    if not _looks_equirect(width, height, spherical):
        raise MCPVideoError(
            f"Not a 360 equirect source ({width}x{height}). Use a stitched 2:1 360 MP4 export.",
            error_type="validation_error",
            code="not_360_equirect",
        )
    digest = hashlib.sha256(Path(resolved).read_bytes()).hexdigest()
    return {
        "path": resolved,
        "sha256": f"sha256:{digest}",
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "projection": "equirect",
        "spherical_metadata": spherical,
    }


def _probe_geometry(path: str) -> tuple[int, int, float, bool]:
    payload = _run_ffprobe_json(path)
    stream = next((item for item in payload.get("streams") or [] if item.get("codec_type") == "video"), None)
    if stream is None:
        raise InputFileError(path, "No video stream")
    try:
        width = int(stream["width"])
        height = int(stream["height"])
        duration = float(payload.get("format", {}).get("duration") or stream.get("duration") or 0.0)
    except (KeyError, TypeError, ValueError) as exc:
        raise InputFileError(path, "Could not read video geometry") from exc
    if duration <= 0:
        raise InputFileError(path, "Could not read video duration")
    tags = {**(payload.get("format", {}).get("tags") or {}), **(stream.get("tags") or {})}
    blob = " ".join(f"{key}={value}" for key, value in tags.items()).lower()
    spherical = "spherical" in blob or "equirect" in blob
    return width, height, duration, spherical


def _looks_equirect(width: int, height: int, spherical: bool) -> bool:
    if height <= 0 or width <= 0:
        return False
    ratio = width / height
    near_two = abs(ratio - SPHERE_EQUIRECT_ASPECT) <= SPHERE_EQUIRECT_ASPECT_TOLERANCE
    return near_two or spherical
