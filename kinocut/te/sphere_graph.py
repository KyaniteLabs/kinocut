"""Single-pass FFmpeg graphs for 360 window composition."""

from __future__ import annotations

from typing import Any

from kinocut.defaults import (
    DEFAULT_SPHERE_FOV,
    DEFAULT_SPHERE_PIP_MARGIN,
    DEFAULT_SPHERE_TEMP_CRF,
    DEFAULT_SPHERE_TEMP_PRESET,
)
from kinocut.engine_runtime_utils import _quality_args
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _format_ffmpeg_number, _run_ffmpeg, _validate_output_path
from kinocut.te.sphere_filters import camera_by_id, v360_filter


def render_window_single_pass(
    plan: dict[str, Any],
    cam_ids: list[str],
    *,
    layout: str,
    start: float,
    end: float,
    dest: str,
    width: int,
    height: int,
) -> str:
    """Decode the sphere once and compose split/pip/switch in one encode."""
    _validate_output_path(dest)
    duration = max(0.05, float(end) - float(start))
    if layout == "split" and len(cam_ids) >= 2:
        graph = _split_graph(plan, cam_ids, width, height)
    elif layout == "pip" and len(cam_ids) >= 2:
        graph = _pip_graph(plan, cam_ids, width, height)
    elif layout == "switch" and len(cam_ids) >= 2:
        graph = _switch_graph(plan, cam_ids, duration, width, height)
    else:
        raise MCPVideoError(
            f"Unknown layout {layout!r}.",
            error_type="validation_error",
            code="invalid_sphere_layout",
        )
    _run_ffmpeg(
        [
            "-ss",
            f"{float(start):.3f}",
            "-i",
            plan["source"]["path"],
            "-t",
            f"{duration:.3f}",
            "-filter_complex",
            graph,
            "-map",
            "[vout]",
            "-map",
            "0:a?",
            "-c:v",
            "libx264",
            *_quality_args(crf=DEFAULT_SPHERE_TEMP_CRF, preset=DEFAULT_SPHERE_TEMP_PRESET),
            "-c:a",
            "aac",
            "-shortest",
            dest,
        ]
    )
    return dest


def _split_graph(plan: dict[str, Any], cam_ids: list[str], width: int, height: int) -> str:
    left_w = max(16, width // 2)
    right_w = max(16, width - left_w)
    left = v360_filter(_camera(plan, cam_ids[0]), width=left_w, height=height)
    right = v360_filter(_camera(plan, cam_ids[1]), width=right_w, height=height)
    return f"[0:v]{left}[left];[0:v]{right}[right];[left][right]hstack=inputs=2[vout]"


def _pip_graph(plan: dict[str, Any], cam_ids: list[str], width: int, height: int) -> str:
    pip_w = max(16, width // 3)
    pip_h = max(16, height // 3)
    margin = _format_ffmpeg_number(DEFAULT_SPHERE_PIP_MARGIN)
    base = v360_filter(_camera(plan, cam_ids[0]), width=width, height=height)
    pip = v360_filter(_camera(plan, cam_ids[1]), width=pip_w, height=pip_h)
    return (
        f"[0:v]{base}[base];[0:v]{pip},format=rgba,colorchannelmixer=aa=0.8[ov];"
        f"[base][ov]overlay=main_w-overlay_w-{margin}:main_h-overlay_h-{margin}[vout]"
    )


def _switch_graph(plan: dict[str, Any], cam_ids: list[str], duration: float, width: int, height: int) -> str:
    span = duration / max(1, len(cam_ids))
    parts: list[str] = []
    labels: list[str] = []
    cursor = 0.0
    for offset, cam_id in enumerate(cam_ids):
        stop = duration if offset == len(cam_ids) - 1 else cursor + span
        filt = v360_filter(_camera(plan, cam_id), width=width, height=height)
        trim_s = _format_ffmpeg_number(cursor)
        trim_e = _format_ffmpeg_number(stop)
        label = f"c{offset}"
        parts.append(f"[0:v]trim=start={trim_s}:end={trim_e},setpts=PTS-STARTPTS,{filt}[{label}]")
        labels.append(f"[{label}]")
        cursor = stop
    concat = "".join(labels) + f"concat=n={len(labels)}:v=1:a=0[vout]"
    return ";".join([*parts, concat])


def _camera(plan: dict[str, Any], camera_id: str) -> dict[str, Any]:
    camera = dict(camera_by_id(plan, camera_id))
    camera["fov"] = camera.get("fov", DEFAULT_SPHERE_FOV)
    return camera
