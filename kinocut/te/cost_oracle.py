"""Universal dry-run cost/time oracle (TE.7) — local estimates, not cloud billing."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError

# Conservative local-machine heuristics (seconds of wall time per second of media).
_OP_FACTORS: dict[str, float] = {
    "trim": 0.05,
    "merge": 0.2,
    "resize": 0.4,
    "subtitles": 0.35,
    "repurpose": 1.2,
    "stabilize": 2.0,
    "upscale": 8.0,
    "transcribe": 1.5,
    "workflow": 1.0,
    "still_package": 0.1,
    "default": 0.5,
}


def estimate_operation(
    operation: str,
    *,
    duration_seconds: float,
    complexity: float = 1.0,
) -> dict[str, Any]:
    """Estimate wall-clock and relative cost units for a local operation.

    Cost units are dimensionless (not USD). Agents should not treat them as
    provider prices.
    """
    if duration_seconds < 0:
        raise MCPVideoError(
            "duration_seconds must be >= 0",
            error_type="validation_error",
            code="invalid_duration",
        )
    if complexity <= 0:
        raise MCPVideoError(
            "complexity must be > 0",
            error_type="validation_error",
            code="invalid_complexity",
        )
    op = (operation or "default").strip().lower().replace("-", "_")
    factor = _OP_FACTORS.get(op, _OP_FACTORS["default"])
    est = duration_seconds * factor * complexity
    return {
        "artifact_kind": "operation_estimate",
        "operation": op,
        "duration_seconds": duration_seconds,
        "complexity": complexity,
        "estimated_wall_seconds": round(est, 3),
        "estimated_cost_units": round(est * 0.01, 4),
        "currency": None,
        "notes": "Local heuristic only; not a cloud invoice.",
        "dry_run": True,
    }
