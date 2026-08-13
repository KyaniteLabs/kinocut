"""Extract per-camera stills from a 360 assembly plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_SPHERE_FOV, DEFAULT_STORYBOARD_HEIGHT, DEFAULT_STORYBOARD_WIDTH
from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_output_path
from kinocut.te.sphere_filters import camera_by_id, v360_filter
from kinocut.te.sphere_plan import validate_sphere_plan


def storyboard_sphere_plan(plan: dict[str, Any], output_dir: str, *, timestamp: float | None = None) -> dict[str, Any]:
    """Write one PNG per camera. Mutates a copy of the plan with stills."""
    current = validate_sphere_plan(dict(plan))
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    source = current["source"]["path"]
    duration = float(current["source"]["duration_seconds"])
    when = 0.0 if timestamp is None else float(timestamp)
    if when < 0 or when >= duration:
        when = max(0.0, min(duration * 0.1, duration - 0.05))
    stills: list[dict[str, Any]] = []
    for camera in current["cameras"]:
        dest = root / f"{camera['id']}.png"
        _extract_still(source, camera, when, dest)
        stills.append({"camera_id": camera["id"], "path": str(dest.resolve()), "timestamp": when})
    current["stills"] = stills
    return current


def _extract_still(source: str, camera: dict[str, Any], timestamp: float, dest: Path) -> None:
    _validate_output_path(str(dest))
    filt = v360_filter(
        {**camera, "fov": camera.get("fov", DEFAULT_SPHERE_FOV)},
        width=DEFAULT_STORYBOARD_WIDTH,
        height=DEFAULT_STORYBOARD_HEIGHT,
    )
    _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            source,
            "-frames:v",
            "1",
            "-vf",
            filt,
            str(dest),
        ]
    )
    if not dest.is_file() or dest.stat().st_size <= 0:
        from kinocut.errors import MCPVideoError

        raise MCPVideoError(
            f"360 still was not written: {dest}",
            error_type="processing_error",
            code="sphere_still_failed",
        )


def extract_camera_clip(
    plan: dict[str, Any],
    camera_id: str,
    *,
    start: float,
    end: float,
    output_path: str,
    width: int,
    height: int,
) -> str:
    """Extract one virtual-camera clip. Used by render."""
    camera = camera_by_id(plan, camera_id)
    _validate_output_path(output_path)
    duration = max(0.05, float(end) - float(start))
    filt = v360_filter(camera, width=width, height=height)
    _run_ffmpeg(
        [
            "-y",
            "-ss",
            f"{float(start):.3f}",
            "-i",
            plan["source"]["path"],
            "-t",
            f"{duration:.3f}",
            "-vf",
            filt,
            output_path,
        ]
    )
    return output_path
