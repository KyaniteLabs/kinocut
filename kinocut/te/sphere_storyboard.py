"""Extract per-camera stills and clips from a 360 assembly plan."""

from __future__ import annotations

import os
import shutil
import tempfile
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
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _atomic_output, _open_staged_writer, _run_ffmpeg, _validate_output_path
from kinocut.publication import validate_artifact_location
from kinocut.te.sphere_filters import camera_by_id, v360_filter
from kinocut.te.sphere_plan import validate_sphere_plan


def _contained_still_dest(root: Path, root_resolved: Path, camera_id: str) -> Path:
    """Resolve a camera still path and prove it stays strictly inside output_dir."""
    if not camera_id or "/" in camera_id or "\\" in camera_id or ".." in camera_id or "\x00" in camera_id:
        raise MCPVideoError(
            "360 camera id escapes storyboard output directory.",
            error_type="validation_error",
            code="unsafe_path",
        )
    dest = root / f"{camera_id}.png"
    dest_resolved = Path(os.path.realpath(str(dest)))
    if dest_resolved.parent != root_resolved:
        raise MCPVideoError(
            "360 still destination escapes storyboard output directory.",
            error_type="validation_error",
            code="unsafe_path",
        )
    return dest


def storyboard_sphere_plan(plan: dict[str, Any], output_dir: str, *, timestamp: float | None = None) -> dict[str, Any]:
    """Write one PNG per camera. Mutates a copy of the plan with stills."""
    current = validate_sphere_plan(dict(plan))
    resolved_root_str = validate_artifact_location(output_dir, "Storyboard output directory")
    if os.path.lexists(resolved_root_str) and not os.path.isdir(resolved_root_str):
        raise MCPVideoError(
            "Storyboard output directory target is not a directory.",
            error_type="validation_error",
            code="unsafe_path",
        )
    root = Path(output_dir)
    root_resolved = Path(resolved_root_str)
    duration = float(current["source"]["duration_seconds"])
    when = 0.0 if timestamp is None else float(timestamp)
    if when < 0 or when >= duration:
        when = max(0.0, min(duration * 0.1, duration - 0.05))
    cameras = list(current["cameras"])
    dests = [_contained_still_dest(root, root_resolved, str(camera["id"])) for camera in cameras]
    _extract_stills_batch(current["source"]["path"], cameras, when, dests)
    current["stills"] = [
        {"camera_id": camera["id"], "path": str(dest.resolve()), "timestamp": when}
        for camera, dest in zip(cameras, dests, strict=True)
    ]
    return current


def _extract_stills_batch(source: str, cameras: list[dict[str, Any]], timestamp: float, dests: list[Path]) -> None:
    for dest in dests:
        _validate_output_path(str(dest))
    with tempfile.TemporaryDirectory(prefix="kinocut-sphere-stills-") as stage_dir:
        staged_dests = [Path(stage_dir) / f"still_{index:03d}.png" for index in range(len(cameras))]
        if len(cameras) == 1:
            _extract_still(source, cameras[0], timestamp, staged_dests[0])
        else:
            parts: list[str] = []
            maps: list[str] = []
            for index, camera in enumerate(cameras):
                filt = v360_filter(_with_fov(camera), width=DEFAULT_STORYBOARD_WIDTH, height=DEFAULT_STORYBOARD_HEIGHT)
                label = f"s{index}"
                parts.append(f"[0:v]{filt}[{label}]")
                maps.extend(["-map", f"[{label}]", "-frames:v", "1", str(staged_dests[index])])
            _run_ffmpeg(["-ss", f"{timestamp:.3f}", "-i", source, "-filter_complex", ";".join(parts), *maps])
            for index, sdest in enumerate(staged_dests, start=1):
                if not sdest.is_file() or sdest.stat().st_size <= 0:
                    raise MCPVideoError(
                        f"360 still {index} of {len(dests)} was not written",
                        error_type="processing_error",
                        code="sphere_still_failed",
                    )
        for sdest, dest in zip(staged_dests, dests, strict=True):
            with (
                _atomic_output(str(dest)) as atomic_stage,
                open(sdest, "rb") as reader,
                _open_staged_writer(atomic_stage) as writer,
            ):
                shutil.copyfileobj(reader, writer)


def _extract_still(source: str, camera: dict[str, Any], timestamp: float, dest: Path) -> None:
    filt = v360_filter(_with_fov(camera), width=DEFAULT_STORYBOARD_WIDTH, height=DEFAULT_STORYBOARD_HEIGHT)
    _run_ffmpeg(["-ss", f"{timestamp:.3f}", "-i", source, "-frames:v", "1", "-vf", filt, str(dest)])
    if not dest.is_file() or dest.stat().st_size <= 0:
        raise MCPVideoError(
            "360 still was not written",
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
    with _atomic_output(output_path) as staged:
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
                staged,
            ]
        )
    return output_path


def _with_fov(camera: dict[str, Any]) -> dict[str, Any]:
    return {**camera, "fov": camera.get("fov", DEFAULT_SPHERE_FOV)}
