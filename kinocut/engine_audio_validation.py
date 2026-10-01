"""Strict finite-number validation shared by audio editing operations."""

import math

from .errors import MCPVideoError


def _audio_number(value: object, name: str, low: float, high: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter")
    try:
        result = float(value)
    except OverflowError:
        raise MCPVideoError(
            f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter"
        ) from None
    if not math.isfinite(result):
        raise MCPVideoError(f"{name} must be a finite number", error_type="validation_error", code="invalid_parameter")
    if not low <= result <= high:
        raise MCPVideoError(
            f"{name} must be {low} to {high}, got {value}", error_type="validation_error", code="invalid_parameter"
        )
    return result
