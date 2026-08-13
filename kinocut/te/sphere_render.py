"""Render an approved 360 assembly plan to a flat 16:9 or 9:16 file."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kinocut.defaults import DEFAULT_QUALITY_GATE_SCORE
from kinocut.engine_merge import merge
from kinocut.engine_overlay import overlay_video
from kinocut.engine_split_screen import split_screen
from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_output_path
from kinocut.quality_guardrails import assert_quality
from kinocut.te.sphere_plan import require_approved
from kinocut.te.sphere_storyboard import extract_camera_clip

logger = logging.getLogger(__name__)


def render_sphere_plan(
    plan: dict[str, Any],
    output_path: str,
    *,
    work_dir: str | None = None,
    allow_fail: bool = False,
    min_score: float | None = None,
) -> dict[str, Any]:
    """Extract cameras and assemble split/pip/switch/single. Requires approved."""
    current = require_approved(plan)
    _validate_output_path(output_path)
    root = Path(work_dir or Path(output_path).resolve().parent / "_sphere_work")
    root.mkdir(parents=True, exist_ok=True)
    pieces = [_render_window(current, window, root, index) for index, window in enumerate(current["windows"])]
    if len(pieces) == 1:
        Path(pieces[0]).replace(output_path)
    else:
        merge(pieces, output_path=output_path)
    gate = _maybe_quality(output_path, allow_fail=allow_fail, min_score=min_score)
    writer = current.get("writer") or {}
    return {
        "artifact_kind": "360_assembly_receipt",
        "output_path": output_path,
        "source": current["source"],
        "cameras": current["cameras"],
        "layout": current["layout"],
        "writer": writer,
        "status": "rendered",
        "quality": gate,
    }


def _render_window(plan: dict[str, Any], window: dict[str, Any], root: Path, index: int) -> str:
    layout = str(window.get("layout") or plan["layout"])
    cam_ids = list(window["cameras"])
    start = float(window["start"])
    end = float(window["end"])
    width = int(plan["output"]["width"])
    height = int(plan["output"]["height"])
    dest = str(root / f"window-{index}.mp4")
    if layout == "single" or len(cam_ids) == 1:
        return extract_camera_clip(plan, cam_ids[0], start=start, end=end, output_path=dest, width=width, height=height)
    if layout == "split":
        return _render_split(plan, cam_ids, start, end, dest, width, height, root, index)
    if layout == "pip":
        return _render_pip(plan, cam_ids, start, end, dest, width, height, root, index)
    if layout == "switch":
        return _render_switch(plan, cam_ids, start, end, dest, width, height, root, index)
    raise MCPVideoError(
        f"Unknown layout {layout!r}.",
        error_type="validation_error",
        code="invalid_sphere_layout",
    )


def _render_split(
    plan: dict[str, Any],
    cam_ids: list[str],
    start: float,
    end: float,
    dest: str,
    width: int,
    height: int,
    root: Path,
    index: int,
) -> str:
    left_w = max(16, width // 2)
    left = extract_camera_clip(
        plan, cam_ids[0], start=start, end=end, output_path=str(root / f"w{index}-a.mp4"), width=left_w, height=height
    )
    right = extract_camera_clip(
        plan,
        cam_ids[1],
        start=start,
        end=end,
        output_path=str(root / f"w{index}-b.mp4"),
        width=width - left_w,
        height=height,
    )
    split_screen(left, right, layout="side-by-side", output_path=dest)
    return dest


def _render_pip(
    plan: dict[str, Any],
    cam_ids: list[str],
    start: float,
    end: float,
    dest: str,
    width: int,
    height: int,
    root: Path,
    index: int,
) -> str:
    base = extract_camera_clip(
        plan, cam_ids[0], start=start, end=end, output_path=str(root / f"w{index}-base.mp4"), width=width, height=height
    )
    pip = extract_camera_clip(
        plan,
        cam_ids[1],
        start=start,
        end=end,
        output_path=str(root / f"w{index}-pip.mp4"),
        width=max(16, width // 3),
        height=max(16, height // 3),
    )
    overlay_video(base, pip, position="bottom-right", output_path=dest)
    return dest


def _render_switch(
    plan: dict[str, Any],
    cam_ids: list[str],
    start: float,
    end: float,
    dest: str,
    width: int,
    height: int,
    root: Path,
    index: int,
) -> str:
    span = (end - start) / max(1, len(cam_ids))
    clips: list[str] = []
    cursor = start
    for offset, cam_id in enumerate(cam_ids):
        stop = end if offset == len(cam_ids) - 1 else cursor + span
        clips.append(
            extract_camera_clip(
                plan,
                cam_id,
                start=cursor,
                end=stop,
                output_path=str(root / f"w{index}-sw{offset}.mp4"),
                width=width,
                height=height,
            )
        )
        cursor = stop
    merge(clips, output_path=dest)
    return dest


def _maybe_quality(output_path: str, *, allow_fail: bool, min_score: float | None) -> dict[str, Any]:
    score = DEFAULT_QUALITY_GATE_SCORE if min_score is None else float(min_score)
    try:
        report = assert_quality(output_path, min_score=score)
        return {"passed": True, "report": report}
    except Exception as exc:
        logger.warning("360 assembly quality gate failed: %s", exc)
        if allow_fail:
            return {"passed": False, "quality_gate_failed": True, "detail": str(exc)[:200]}
        raise
