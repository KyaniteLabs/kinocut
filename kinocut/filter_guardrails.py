"""Parameter bounds validation for video/audio filters."""

from __future__ import annotations

from typing import Any

from .validation import FILTER_PARAMETER_BOUNDS


def validate_filter_params(filter_type: str, params: dict[str, Any]) -> list[str]:
    """Validate filter parameters against known bounds.

    Returns a list of warning/error messages. Empty list means clean.
    """
    warnings: list[str] = []
    bounds = FILTER_PARAMETER_BOUNDS.get(filter_type)
    if not bounds:
        return warnings

    for key, (lo, hi) in bounds.items():
        value = params.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            warnings.append(f"Parameter '{key}' must be numeric, got {type(value).__name__}")
            continue
        if value < lo or value > hi:
            warnings.append(
                f"Parameter '{key}'={value} is outside recommended range "
                f"[{lo}, {hi}] for filter '{filter_type}'. "
                f"This may produce unusable output."
            )
    return warnings


def clamp_filter_params(filter_type: str, params: dict[str, Any]) -> dict[str, Any]:
    """Clamp filter parameters to their safe bounds.

    Returns a new dict with clamped values.
    """
    clamped = dict(params)
    bounds = FILTER_PARAMETER_BOUNDS.get(filter_type)
    if not bounds:
        return clamped

    for key, (lo, hi) in bounds.items():
        value = clamped.get(key)
        if isinstance(value, (int, float)):
            clamped[key] = max(lo, min(hi, float(value)))
    return clamped
