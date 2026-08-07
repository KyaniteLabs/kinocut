"""Narrative / retention heuristics (P3.4) — first-15s check."""

from __future__ import annotations

from typing import Any

from kinocut.ffmpeg_helpers import _get_video_duration, _validate_input_path


def run_narrative_qc(
    input_path: str,
    *,
    first_seconds: float = 15.0,
    min_hook_seconds: float = 1.0,
) -> dict[str, Any]:
    """Offline retention heuristics without claiming ML ranking."""
    path = _validate_input_path(input_path)
    duration = float(_get_video_duration(path))
    findings: list[dict[str, Any]] = []
    if duration < min_hook_seconds:
        findings.append(
            {
                "check_id": "narrative.duration",
                "severity": "fail",
                "message": f"duration {duration:.2f}s shorter than min hook {min_hook_seconds}s",
            }
        )
    elif duration < first_seconds:
        findings.append(
            {
                "check_id": "narrative.first15",
                "severity": "warn",
                "message": f"clip shorter than {first_seconds}s first-window ({duration:.2f}s total)",
                "time_range": {"start": 0.0, "end": duration},
            }
        )
    else:
        findings.append(
            {
                "check_id": "narrative.first15",
                "severity": "info",
                "message": f"first {first_seconds}s window available for hook review",
                "time_range": {"start": 0.0, "end": first_seconds},
            }
        )
    # Simple end-card heuristic: last 2s exists
    if duration >= 2.0:
        findings.append(
            {
                "check_id": "narrative.end_card_window",
                "severity": "info",
                "message": "end window present for CTA/card review",
                "time_range": {"start": max(0.0, duration - 2.0), "end": duration},
            }
        )
    blocked = any(f["severity"] == "fail" for f in findings)
    return {
        "artifact_kind": "narrative_qc",
        "input_path": path,
        "duration_seconds": duration,
        "findings": findings,
        "verdict": "fail" if blocked else "pass",
        "blocked": blocked,
    }
