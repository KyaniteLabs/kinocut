"""Shared v360 filter construction for 360 extracts."""

from __future__ import annotations

from typing import Any

from kinocut.ffmpeg_helpers import _format_ffmpeg_number


def v360_filter(camera: dict[str, Any], *, width: int, height: int) -> str:
    """Build an escaped-number v360 rectilinear extract filter."""
    yaw = _format_ffmpeg_number(camera["yaw"])
    pitch = _format_ffmpeg_number(camera["pitch"])
    roll = _format_ffmpeg_number(camera["roll"])
    fov = _format_ffmpeg_number(camera["fov"])
    return f"v360=e:flat:yaw={yaw}:pitch={pitch}:roll={roll}:h_fov={fov}:w={int(width)}:h={int(height)}"


def camera_by_id(plan: dict[str, Any], camera_id: str) -> dict[str, Any]:
    for camera in plan.get("cameras") or []:
        if camera.get("id") == camera_id:
            return camera
    raise KeyError(camera_id)
