"""Blend-mode allowlist and full-canvas geometry validation for composite-layers.

Split into its own module to keep engine_composite_layers.py under the
architecture guardrail's per-module line limit (see
tests/test_architecture_guardrails.py::test_engine_modules_stay_below_project_size_limit).
"""

from __future__ import annotations

from typing import Any

from .errors import MCPVideoError

# Full-canvas blend modes accepted this release, mapped through an explicit
# allowlist to FFmpeg ``blend`` filter ``all_mode`` tokens (never interpolated
# from the raw spec value). "normal" stays on the existing overlay path.
BLEND_ALL_MODES = {mode: mode for mode in ("multiply", "screen", "overlay", "darken", "lighten")}
SUPPORTED_BLEND_MODES = frozenset({"normal", *BLEND_ALL_MODES})


def validate_blend_geometry(layer: Any) -> None:
    """Fail closed unless a non-normal blend layer is full-canvas: position
    {0,0}, full opacity, no scale/width/height/rotation/pivot/mask/matte/
    start/duration. Rotation composes with the overlay path only."""
    reasons: list[str] = []
    if layer.position["x"] != 0 or layer.position["y"] != 0:
        reasons.append("a non-zero position")
    if layer.scale is not None or layer.width is not None or layer.height is not None:
        reasons.append("a scale/width/height transform")
    if getattr(layer, "rotation", None) is not None or getattr(layer, "pivot", None) is not None:
        reasons.append("a rotation/pivot transform")
    if layer.mask is not None or layer.matte is not None:
        reasons.append("a mask/matte")
    if layer.start is not None or layer.duration is not None:
        reasons.append("a start/duration timing window")
    if layer.opacity != 1.0:
        reasons.append("opacity below 1.0")
    if reasons:
        raise MCPVideoError(
            f"layer {layer.id!r} blend {layer.blend!r} combines with {', '.join(reasons)}; "
            "non-normal blend is full-canvas-only this release (deferred otherwise)",
            error_type="validation_error",
            code="unsupported_blend_geometry",
        )
