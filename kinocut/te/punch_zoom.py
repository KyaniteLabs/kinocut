"""Auto-zoom punch-ins on cuts (TE.5) — plan + optional ffmpeg filter string."""

from __future__ import annotations

from typing import Any, Sequence

from kinocut.errors import MCPVideoError


def plan_punch_zooms(
    cut_times: Sequence[float],
    *,
    zoom: float = 1.15,
    duration_seconds: float = 0.35,
) -> dict[str, Any]:
    if zoom < 1.0 or zoom > 2.0:
        raise MCPVideoError("zoom must be in [1.0, 2.0]", error_type="validation_error", code="bad_zoom")
    if duration_seconds <= 0:
        raise MCPVideoError("duration_seconds must be > 0", error_type="validation_error", code="bad_duration")
    events = []
    for i, t in enumerate(cut_times):
        start = float(t)
        events.append(
            {
                "event_id": f"punch-{i+1:03d}",
                "time": start,
                "zoom": zoom,
                "duration_seconds": duration_seconds,
                "filter_hint": (
                    f"zoompan=z='if(between(t,{start},{start+duration_seconds}),{zoom},1)':"
                    f"d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
                ),
            }
        )
    return {
        "artifact_kind": "punch_zoom_plan",
        "event_count": len(events),
        "events": events,
        "notes": "Plan only — wire into workflow/render for pixel apply.",
    }
