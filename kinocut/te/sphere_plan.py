"""360 assembly plan schema, presets, and human approve/reject."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from kinocut.defaults import (
    DEFAULT_SPHERE_FOV,
    DEFAULT_SPHERE_OUTPUT_HEIGHT,
    DEFAULT_SPHERE_OUTPUT_WIDTH,
    DEFAULT_SPHERE_TABLE_PITCH,
    DEFAULT_SPHERE_VERTICAL_HEIGHT,
    DEFAULT_SPHERE_VERTICAL_WIDTH,
)
from kinocut.errors import MCPVideoError
from kinocut.te.sphere_probe import probe_360_source
from kinocut.validation import SPHERE_LAYOUTS, SPHERE_PRESETS, SPHERE_WRITER_KINDS

_FRONT = {"id": "front", "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": DEFAULT_SPHERE_FOV}
_BACK = {"id": "back", "yaw": 180.0, "pitch": 0.0, "roll": 0.0, "fov": DEFAULT_SPHERE_FOV}

_PRESETS: dict[str, dict[str, Any]] = {
    "front_back": {
        "layout": "split",
        "cameras": (dict(_FRONT), dict(_BACK)),
    },
    "desk": {
        "layout": "split",
        "cameras": (
            {"id": "talent", "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": DEFAULT_SPHERE_FOV},
            {"id": "screens", "yaw": 180.0, "pitch": 0.0, "roll": 0.0, "fov": DEFAULT_SPHERE_FOV},
        ),
    },
    "table": {
        "layout": "switch",
        "cameras": (
            {"id": "talent", "yaw": 0.0, "pitch": 0.0, "roll": 0.0, "fov": DEFAULT_SPHERE_FOV},
            {
                "id": "table",
                "yaw": 180.0,
                "pitch": DEFAULT_SPHERE_TABLE_PITCH,
                "roll": 0.0,
                "fov": DEFAULT_SPHERE_FOV,
            },
        ),
    },
}


def propose_sphere_plan(
    source: str,
    *,
    preset: str = "desk",
    layout: str | None = None,
    aspect: str = "16:9",
    writer_kind: str = "heuristic",
) -> dict[str, Any]:
    """Build a proposed plan from a preset. Does not render."""
    if preset not in SPHERE_PRESETS or preset not in _PRESETS:
        raise MCPVideoError(
            f"Unknown 360 preset {preset!r}. Use front_back, desk, or table.",
            error_type="validation_error",
            code="invalid_sphere_preset",
        )
    probed = probe_360_source(source)
    spec = _PRESETS[preset]
    chosen_layout = layout or spec["layout"]
    width, height = _output_size(aspect)
    cameras = [dict(cam) for cam in spec["cameras"]]
    if writer_kind == "single":
        cameras = cameras[:1]
        chosen_layout = "single"
    windows = _default_windows(probed["duration_seconds"], cameras, chosen_layout)
    plan = {
        "artifact_kind": "360_assembly_plan",
        "schema_version": 1,
        "source": probed,
        "projection": "equirect",
        "preset": preset,
        "output": {"aspect": aspect, "width": width, "height": height},
        "cameras": cameras,
        "layout": chosen_layout,
        "windows": windows,
        "writer": {"kind": writer_kind, "provider": None, "model": None},
        "status": "proposed",
        "stills": [],
    }
    return validate_sphere_plan(plan)


def validate_sphere_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Fail closed on a malformed assembly plan. Returns the same dict."""
    if not isinstance(plan, dict) or plan.get("artifact_kind") != "360_assembly_plan":
        raise MCPVideoError(
            "Expected a 360_assembly_plan.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )
    if plan.get("schema_version") != 1:
        raise MCPVideoError("Unsupported 360 plan schema.", error_type="validation_error", code="invalid_sphere_plan")
    layout = plan.get("layout")
    if layout not in SPHERE_LAYOUTS:
        raise MCPVideoError(
            f"Unknown layout {layout!r}. Use single, split, pip, or switch.",
            error_type="validation_error",
            code="invalid_sphere_layout",
        )
    cameras = plan.get("cameras")
    if not isinstance(cameras, list) or not cameras:
        raise MCPVideoError("360 plan requires cameras.", error_type="validation_error", code="invalid_sphere_plan")
    _validate_cameras(cameras)
    _validate_windows(plan.get("windows"), {str(cam["id"]) for cam in cameras})
    writer = plan.get("writer") or {}
    if writer.get("kind") not in SPHERE_WRITER_KINDS:
        raise MCPVideoError(
            "360 plan writer kind must be heuristic, single, or model.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )
    if plan.get("status") not in {"proposed", "approved", "rejected"}:
        raise MCPVideoError("360 plan status is invalid.", error_type="validation_error", code="invalid_sphere_plan")
    _validate_source(plan.get("source"))
    _validate_output(plan.get("output"))
    return plan


def decide_sphere_plan(plan: dict[str, Any], decision: str, *, layout: str | None = None) -> dict[str, Any]:
    """Approve or reject a proposed plan. Optional layout override on approve."""
    current = validate_sphere_plan(deepcopy(plan))
    verb = (decision or "").strip().lower()
    if verb in {"approve", "accept"}:
        if layout is not None:
            current["layout"] = layout
            for window in current.get("windows") or []:
                window["layout"] = layout
        current["status"] = "approved"
        return validate_sphere_plan(current)
    if verb == "reject":
        current["status"] = "rejected"
        return current
    raise MCPVideoError(
        "360 review decision must be approve, accept, or reject.",
        error_type="validation_error",
        code="invalid_sphere_decision",
    )


def require_approved(plan: dict[str, Any]) -> dict[str, Any]:
    current = validate_sphere_plan(plan)
    if current.get("status") != "approved":
        raise MCPVideoError(
            "360 assembly render requires an approved plan.",
            error_type="validation_error",
            code="human_apply_required",
        )
    return current


def _output_size(aspect: str) -> tuple[int, int]:
    if aspect == "9:16":
        return DEFAULT_SPHERE_VERTICAL_WIDTH, DEFAULT_SPHERE_VERTICAL_HEIGHT
    if aspect == "16:9":
        return DEFAULT_SPHERE_OUTPUT_WIDTH, DEFAULT_SPHERE_OUTPUT_HEIGHT
    raise MCPVideoError(
        f"Unsupported output aspect {aspect!r}. Use 16:9 or 9:16.",
        error_type="validation_error",
        code="invalid_sphere_aspect",
    )


def _default_windows(duration: float, cameras: list[dict[str, Any]], layout: str) -> list[dict[str, Any]]:
    ids = [str(cam["id"]) for cam in cameras]
    if layout == "switch" and len(ids) >= 2:
        mid = duration / 2.0
        return [
            {"id": "w1", "start": 0.0, "end": mid, "cameras": [ids[0]], "layout": "single"},
            {"id": "w2", "start": mid, "end": duration, "cameras": [ids[1]], "layout": "single"},
        ]
    return [{"id": "w1", "start": 0.0, "end": duration, "cameras": ids, "layout": layout}]


def _validate_source(source: Any) -> None:
    if not isinstance(source, dict) or not source.get("path"):
        raise MCPVideoError(
            "360 plan requires source.path.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )
    try:
        duration = float(source.get("duration_seconds", 0))
    except (TypeError, ValueError) as exc:
        raise MCPVideoError(
            "360 plan source.duration_seconds must be numeric.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        ) from exc
    if duration <= 0 or not str(source.get("sha256") or "").startswith("sha256:"):
        raise MCPVideoError(
            "360 plan source needs a positive duration and sha256 digest.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )


def _validate_output(output: Any) -> None:
    if not isinstance(output, dict):
        raise MCPVideoError(
            "360 plan requires output width, height, and aspect.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )
    aspect = output.get("aspect")
    if aspect not in {"16:9", "9:16"}:
        raise MCPVideoError(
            "360 plan output.aspect must be 16:9 or 9:16.",
            error_type="validation_error",
            code="invalid_sphere_aspect",
        )
    try:
        width = int(output.get("width"))
        height = int(output.get("height"))
    except (TypeError, ValueError) as exc:
        raise MCPVideoError(
            "360 plan output width and height must be integers.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        ) from exc
    if width < 1 or height < 1:
        raise MCPVideoError(
            "360 plan output dimensions must be positive.",
            error_type="validation_error",
            code="invalid_sphere_plan",
        )


def _validate_cameras(cameras: list[dict[str, Any]]) -> None:
    seen: set[str] = set()
    for camera in cameras:
        cam_id = str(camera.get("id") or "")
        if not cam_id or cam_id in seen:
            raise MCPVideoError(
                "Each 360 camera needs a unique id.",
                error_type="validation_error",
                code="invalid_sphere_plan",
            )
        seen.add(cam_id)
        for key in ("yaw", "pitch", "roll", "fov"):
            try:
                float(camera[key])
            except (KeyError, TypeError, ValueError) as exc:
                raise MCPVideoError(
                    f"Camera {cam_id!r} is missing a numeric {key}.",
                    error_type="validation_error",
                    code="invalid_sphere_plan",
                ) from exc


def _validate_windows(windows: Any, camera_ids: set[str]) -> None:
    if not isinstance(windows, list) or not windows:
        raise MCPVideoError("360 plan requires windows.", error_type="validation_error", code="invalid_sphere_plan")
    for window in windows:
        start = float(window.get("start", -1))
        end = float(window.get("end", -1))
        if end <= start:
            raise MCPVideoError(
                "Each 360 window needs end greater than start.",
                error_type="validation_error",
                code="invalid_sphere_plan",
            )
        used = window.get("cameras") or []
        if not used or any(cam_id not in camera_ids for cam_id in used):
            raise MCPVideoError(
                "Window cameras must exist on the plan.",
                error_type="validation_error",
                code="invalid_sphere_plan",
            )
        layout = window.get("layout")
        if layout is not None and layout not in SPHERE_LAYOUTS:
            raise MCPVideoError(
                f"Unknown window layout {layout!r}.",
                error_type="validation_error",
                code="invalid_sphere_layout",
            )
