"""Detect stitched equirect 360 sources. Reject raw vendor dual-fisheye."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_HASH_CACHE_MAX, DEFAULT_HASH_CHUNK_BYTES
from kinocut.errors import InputFileError, MCPVideoError
from kinocut.ffmpeg_helpers import _run_ffprobe_json, _validate_input_path
from kinocut.validation import (
    SPHERE_EQUIRECT_ASPECT,
    SPHERE_EQUIRECT_ASPECT_TOLERANCE,
    SPHERE_RAW_SUFFIXES,
    SPHERE_SPHERICAL_MARKERS,
)

_HASH_CACHE: dict[tuple[str, int, int], str] = {}

_VENDOR_HINTS = (
    ("insta360", "insta360"),
    ("insta 360", "insta360"),
    ("theta", "ricoh"),
    ("ricoh", "ricoh"),
    ("gopro", "gopro"),
    ("osmo", "dji"),
    ("dji", "dji"),
)


def probe_360_source(path: str) -> dict[str, Any]:
    """Return source facts if ``path`` is a stitched equirect video."""
    _reject_raw_container(path)
    resolved = _validate_input_path(path)
    width, height, duration, spherical, tag_blob = _probe_geometry(resolved)
    if not _looks_equirect(width, height, spherical):
        raise MCPVideoError(
            f"Not a 360 equirect source ({width}x{height}). Export a stitched "
            "2:1 equirect MP4 (any camera). Raw dual-fisheye is not accepted.",
            error_type="validation_error",
            code="not_360_equirect",
        )
    via = "spherical_metadata" if spherical else "aspect"
    return {
        "path": resolved,
        "sha256": _file_sha256(resolved),
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "projection": "equirect",
        "spherical_metadata": spherical,
        "accepted_via": via,
        "vendor_hint": _vendor_hint(resolved, tag_blob),
    }


def _reject_raw_container(path: str) -> None:
    suffix = Path(str(path)).suffix.lower()
    if suffix not in SPHERE_RAW_SUFFIXES:
        return
    if suffix == ".insv":
        raise MCPVideoError(
            "Raw Insta360 .insv cannot be stitched here. Export a stitched "
            "equirect MP4 from the camera app or studio first.",
            error_type="validation_error",
            code="not_insv_export",
            suggested_action={
                "auto_fix": False,
                "description": "Export a stitched equirect MP4, then retry.",
            },
        )
    raise MCPVideoError(
        f"Raw 360 container {suffix} is not a stitched equirect. Export MP4 "
        "from the camera app (GoPro Player, Insta360, Ricoh, DJI) first.",
        error_type="validation_error",
        code="not_raw_360",
        suggested_action={
            "auto_fix": False,
            "description": "Export a stitched equirect MP4, then retry.",
        },
    )


def _probe_geometry(path: str) -> tuple[int, int, float, bool, str]:
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
    spherical = any(marker in blob for marker in SPHERE_SPHERICAL_MARKERS)
    return width, height, duration, spherical, blob


def _file_sha256(path: str) -> str:
    stat = Path(path).stat()
    key = (str(Path(path).resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _HASH_CACHE.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(DEFAULT_HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    value = "sha256:" + digest.hexdigest()
    if len(_HASH_CACHE) >= DEFAULT_HASH_CACHE_MAX:
        _HASH_CACHE.pop(next(iter(_HASH_CACHE)))
    _HASH_CACHE[key] = value
    return value


def _looks_equirect(width: int, height: int, spherical: bool) -> bool:
    if height <= 0 or width <= 0:
        return False
    ratio = width / height
    near_two = abs(ratio - SPHERE_EQUIRECT_ASPECT) <= SPHERE_EQUIRECT_ASPECT_TOLERANCE
    return near_two or spherical


def _vendor_hint(path: str, tag_blob: str) -> str | None:
    haystack = f"{Path(path).name.lower()} {tag_blob}"
    for token, vendor in _VENDOR_HINTS:
        if token in haystack:
            return vendor
    return None
