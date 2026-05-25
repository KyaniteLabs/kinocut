"""Parameter bounds validation for video/audio filters."""

from __future__ import annotations

from typing import Any

# Per-filter parameter bounds: (min, max)
# Keys match the filter_type values used in engine_filters._filter_map().
_FILTER_BOUNDS: dict[str, dict[str, tuple[float, float]]] = {
    "blur": {"radius": (0.0, 50.0), "strength": (0.0, 5.0)},
    "sharpen": {"amount": (0.0, 3.0)},
    "brightness": {"level": (-1.0, 1.0)},
    "contrast": {"level": (0.0, 3.0)},
    "saturation": {"level": (0.0, 3.0)},
    "vignette": {"angle": (0.0, 6.2832)},  # 0 to 2*PI
    "denoise": {
        "luma_spatial": (0.0, 30.0),
        "chroma_spatial": (0.0, 30.0),
        "luma_tmp": (0.0, 30.0),
        "chroma_tmp": (0.0, 30.0),
    },
    "ken_burns": {"zoom_speed": (0.0001, 0.01)},
    "reverb": {
        "in_gain": (0.0, 1.0),
        "out_gain": (0.0, 1.0),
        "decay": (0.0, 0.9),
    },
    "compressor": {"ratio": (1.0, 20.0)},
    "noise_reduction": {"noise_level": (-60.0, 0.0)},
}


def validate_filter_params(filter_type: str, params: dict[str, Any]) -> list[str]:
    """Validate filter parameters against known bounds.

    Returns a list of warning/error messages. Empty list means clean.
    """
    warnings: list[str] = []
    bounds = _FILTER_BOUNDS.get(filter_type)
    if not bounds:
        return warnings

    for key, (lo, hi) in bounds.items():
        value = params.get(key)
        if value is None:
            continue
        if not isinstance(value, (int, float)):
            warnings.append(
                f"Parameter '{key}' must be numeric, got {type(value).__name__}"
            )
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
    bounds = _FILTER_BOUNDS.get(filter_type)
    if not bounds:
        return clamped

    for key, (lo, hi) in bounds.items():
        value = clamped.get(key)
        if isinstance(value, (int, float)):
            clamped[key] = max(lo, min(hi, float(value)))
    return clamped
