"""Universal dry-run cost/time oracle (TE.7) — local estimates, not cloud billing."""

from __future__ import annotations

import math
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.limits import MAX_ESTIMATE_OPERATION_CHARS

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


def _validated_estimate_number(value: object, name: str, *, positive: bool) -> float:
    code = "invalid_complexity" if positive else "invalid_duration"
    try:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise TypeError
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise MCPVideoError(
            f"{name} must be a finite number",
            error_type="validation_error",
            code=code,
        ) from error
    if not math.isfinite(number) or number < 0 or (positive and number == 0):
        raise MCPVideoError(
            f"{name} must be finite and {'> 0' if positive else '>= 0'}",
            error_type="validation_error",
            code=code,
        )
    return number


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
    if not isinstance(operation, str) or len(operation) > MAX_ESTIMATE_OPERATION_CHARS or not operation.strip():
        raise MCPVideoError(
            f"operation must be a nonempty string of at most {MAX_ESTIMATE_OPERATION_CHARS} characters",
            error_type="validation_error",
            code="invalid_operation",
        )
    duration_seconds = _validated_estimate_number(duration_seconds, "duration_seconds", positive=False)
    complexity = _validated_estimate_number(complexity, "complexity", positive=True)
    op = operation.strip().lower().replace("-", "_")
    factor = _OP_FACTORS.get(op, _OP_FACTORS["default"])
    est = duration_seconds * factor * complexity
    cost_units = est * 0.01
    if not math.isfinite(est) or not math.isfinite(cost_units):
        raise MCPVideoError(
            "Estimate exceeds finite numeric limits",
            error_type="validation_error",
            code="invalid_estimate",
        )
    return {
        "artifact_kind": "operation_estimate",
        "operation": op,
        "duration_seconds": duration_seconds,
        "complexity": complexity,
        "estimated_wall_seconds": round(est, 3),
        "estimated_cost_units": round(cost_units, 4),
        "currency": None,
        "notes": "Local heuristic only; not a cloud invoice.",
        "dry_run": True,
    }
