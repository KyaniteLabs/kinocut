"""Shared value objects and payload builders for visual quality guardrails."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _diagnostic(stage: str, message: str, **extra: Any) -> dict[str, Any]:
    """Create a structured diagnostic payload for analysis fallbacks."""
    payload: dict[str, Any] = {"stage": stage, "message": message}
    payload.update(extra)
    return payload


def _metric(
    name: str,
    value: float | None,
    unit: str,
    **metadata: Any,
) -> dict[str, Any]:
    """Build the explicit metric contract shared by quality surfaces."""
    return {
        "name": name,
        "available": value is not None,
        "value": value,
        "unit": unit,
        **metadata,
    }


@dataclass
class QualityReport:
    """Report from a single quality check."""

    check_name: str
    passed: bool
    score: float
    message: str
    details: dict[str, Any] = field(default_factory=dict)
