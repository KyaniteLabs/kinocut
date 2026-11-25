"""Auto-zoom punch-ins on cuts (TE.5) — plan + optional ffmpeg filter string."""

from __future__ import annotations

import math
from typing import Any
from collections.abc import Sequence

from kinocut.errors import MCPVideoError


def _require_finite_number(value: object, name: str, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code=code)
    result = float(value)
    if not math.isfinite(result):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code=code)
    return result


def plan_punch_zooms(
    cut_times: Sequence[float],
    *,
    zoom: float = 1.15,
    duration_seconds: float = 0.35,
    fps: float = 30.0,
    width: int = 1280,
    height: int = 720,
) -> dict[str, Any]:
    zoom_val = _require_finite_number(zoom, "zoom", "bad_zoom")
    if zoom_val < 1.0 or zoom_val > 2.0:
        raise MCPVideoError("zoom must be in [1.0, 2.0]", error_type="validation_error", code="bad_zoom")
    dur_val = _require_finite_number(duration_seconds, "duration_seconds", "bad_duration")
    if dur_val <= 0:
        raise MCPVideoError("duration_seconds must be > 0", error_type="validation_error", code="bad_duration")
    fps_val = _require_finite_number(fps, "fps", "bad_fps")
    if fps_val <= 0:
        raise MCPVideoError("fps must be > 0", error_type="validation_error", code="bad_fps")
    if (
        isinstance(width, bool)
        or not isinstance(width, int)
        or width < 2
        or isinstance(height, bool)
        or not isinstance(height, int)
        or height < 2
    ):
        raise MCPVideoError(
            "width and height must be integers >= 2", error_type="validation_error", code="bad_dimensions"
        )
    even_w = width + (width % 2)
    even_h = height + (height % 2)
    events = []
    for i, t in enumerate(cut_times):
        start = _require_finite_number(t, "cut_time", "bad_cut_time")
        if start < 0:
            raise MCPVideoError("cut_times must be non-negative", error_type="validation_error", code="bad_cut_time")
        end = start + dur_val
        events.append(
            {
                "event_id": f"punch-{i + 1:03d}",
                "time": start,
                "zoom": zoom_val,
                "duration_seconds": dur_val,
                "filter_hint": (
                    f"zoompan=z='if(between(in_time,{start:.6g},{end:.6g}),{zoom_val:.6g},1)':"
                    f"d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2':"
                    f"s={even_w}x{even_h}:fps={fps_val:g}"
                ),
            }
        )
    return {
        "artifact_kind": "punch_zoom_plan",
        "event_count": len(events),
        "events": events,
        "notes": "Plan only — wire into workflow/render for pixel apply.",
    }
