"""Extract per-camera stills and clips from a 360 assembly plan."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from kinocut.defaults import (
    DEFAULT_SPHERE_FOV,
    DEFAULT_SPHERE_TEMP_CRF,
    DEFAULT_SPHERE_TEMP_PRESET,
    DEFAULT_STORYBOARD_HEIGHT,
    DEFAULT_STORYBOARD_WIDTH,
)
from kinocut.engine_runtime_utils import _quality_args
from kinocut.ffmpeg_helpers import _run_ffmpeg, _validate_output_path
from kinocut.te.sphere_filters import camera_by_id, v360_filter
from kinocut.te.sphere_plan import validate_sphere_plan


def storyboard_sphere_plan(plan: dict[str, Any], output_dir: str, *, timestamp: float | None = None) -> dict[str, Any]:
    """Write one PNG per camera. Mutates a copy of the plan with stills."""
    current = validate_sphere_plan(dict(plan))
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    duration = float(current["source"]["duration_seconds"])
    when = 0.0 if timestamp is None else float(timestamp)
    if when < 0 or when >= duration:
        when = max(0.0, min(duration * 0.1, duration - 0.05))
    cameras = list(current["cameras"])
    dests = [root / f"{camera['id']}.png" for camera in cameras]
    _extract_stills_batch(current["source"]["path"], cameras, when, dests)
    current["stills"] = [
        {"camera_id": camera["id"], "path": str(dest.resolve()), "timestamp": when}
        for camera, dest in zip(cameras, dests, strict=True)
    ]
    return current


def _extract_stills_batch(source: str, cameras: list[dict[str, Any]], timestamp: float, dests: list[Path]) -> None:
    for dest in dests:
        _validate_output_path(str(dest))
    if len(cameras) == 1:
        _extract_still(source, cameras[0], timestamp, dests[0])
        return
    parts: list[str] = []
    maps: list[str] = []
    for index, camera in enumerate(cameras):
        filt = v360_filter(_with_fov(camera), width=DEFAULT_STORYBOARD_WIDTH, height=DEFAULT_STORYBOARD_HEIGHT)
        label = f"s{index}"
        parts.append(f"[0:v]{filt}[{label}]")
        maps.extend(["-map", f"[{label}]", "-frames:v", "1", str(dests[index])])
    _run_ffmpeg(["-ss", f"{timestamp:.3f}", "-i", source, "-filter_complex", ";".join(parts), *maps])
    for dest in dests:
        if not dest.is_file() or dest.stat().st_size <= 0:
            from kinocut.errors import MCPVideoError

            raise MCPVideoError(
                f"360 still was not written: {dest}",
                error_type="processing_error",
                code="sphere_still_failed",
            )


def _extract_still(source: str, camera: dict[str, Any], timestamp: float, dest: Path) -> None:
    _validate_output_path(str(dest))
    filt = v360_filter(_with_fov(camera), width=DEFAULT_STORYBOARD_WIDTH, height=DEFAULT_STORYBOARD_HEIGHT)
    _run_ffmpeg(["-ss", f"{timestamp:.3f}", "-i", source, "-frames:v", "1", "-vf", filt, str(dest)])
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
    filt = v360_filter(_with_fov(camera), width=width, height=height)
    _run_ffmpeg(
        [
            "-ss",
            f"{float(start):.3f}",
            "-i",
            plan["source"]["path"],
            "-t",
            f"{duration:.3f}",
            "-vf",
            filt,
            "-c:v",
            "libx264",
            *_quality_args(crf=DEFAULT_SPHERE_TEMP_CRF, preset=DEFAULT_SPHERE_TEMP_PRESET),
            output_path,
        ]
    )
    return output_path


def _with_fov(camera: dict[str, Any]) -> dict[str, Any]:
    return {**camera, "fov": camera.get("fov", DEFAULT_SPHERE_FOV)}
