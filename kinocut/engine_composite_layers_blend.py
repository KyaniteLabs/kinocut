"""Blend-mode allowlist and geometry validation for composite-layers.

Split into its own module to keep engine_composite_layers.py under the
architecture guardrail's per-module line limit (see
tests/test_architecture_guardrails.py::test_engine_modules_stay_below_project_size_limit).

A non-normal blend layer is accepted in exactly two geometries:

* **full-canvas** -- position ``{0,0}``, no width/height, opacity 1.0; the layer
  is force-scaled to the canvas and blended against the running base.
* **positioned** -- explicit positive-integer ``width``/``height`` and an
  integral, non-negative ``position`` whose rectangle lies fully inside the
  canvas. The running base is cropped to that rectangle, blended same-size with
  the scaled layer, and the result is overlaid back at the position.

Everything else (scale, rotation/pivot, mask/matte, timing windows, opacity
below 1.0, fractional position, partial width/height, out-of-canvas rectangles)
fails closed with ``unsupported_blend_geometry``.
"""

from __future__ import annotations

from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value

# Blend modes accepted this release, mapped through an explicit
# allowlist to FFmpeg ``blend`` filter ``all_mode`` tokens (never interpolated
# from the raw spec value). "normal" stays on the existing overlay path.
BLEND_ALL_MODES = {mode: mode for mode in ("multiply", "screen", "overlay", "darken", "lighten")}
SUPPORTED_BLEND_MODES = frozenset({"normal", *BLEND_ALL_MODES})


def validate_blend_geometry(layer: Any, canvas: Any) -> None:
    """Fail closed unless a non-normal blend layer is full-canvas or a valid
    positioned in-canvas rectangle (see module docstring)."""
    reasons: list[str] = []
    if getattr(layer, "rotation", None) is not None or getattr(layer, "pivot", None) is not None:
        reasons.append("a rotation/pivot transform")
    if layer.mask is not None or layer.matte is not None:
        reasons.append("a mask/matte")
    if layer.start is not None or layer.duration is not None:
        reasons.append("a start/duration timing window")
    if layer.opacity != 1.0:
        reasons.append("opacity below 1.0")
    if layer.scale is not None:
        reasons.append("a scale transform")
    if reasons:
        raise _blend_geometry_error(layer, reasons)

    has_width = layer.width is not None
    has_height = layer.height is not None
    if has_width != has_height:
        # A partial size cannot derive an integral rectangle.
        raise _blend_geometry_error(layer, ["a partial width/height (use both)"])

    px = float(layer.position["x"])
    py = float(layer.position["y"])
    if not (px.is_integer() and py.is_integer()):
        raise _blend_geometry_error(layer, ["a fractional position"])

    if not has_width:
        # Full-canvas branch: position must be exactly {0,0}.
        if px != 0 or py != 0:
            raise _blend_geometry_error(layer, ["a non-zero position without width/height"])
        return

    x, y = int(px), int(py)
    w = int(layer.width)
    h = int(layer.height)
    if x < 0 or y < 0:
        raise _blend_geometry_error(layer, ["a negative position"])
    if x + w > int(canvas.width) or y + h > int(canvas.height):
        raise _blend_geometry_error(layer, ["a rectangle outside the canvas"])


def _blend_geometry_error(layer: Any, reasons: list[str]) -> MCPVideoError:
    return MCPVideoError(
        f"layer {layer.id!r} blend {layer.blend!r} combines with {', '.join(reasons)}; "
        "non-normal blend allows full-canvas or a positioned in-canvas rectangle only "
        "(scale/rotation/mask/timing/opacity/fractional/out-of-canvas are deferred)",
        error_type="validation_error",
        code="unsupported_blend_geometry",
    )


def is_positioned_blend(layer: Any) -> bool:
    """True when a blend layer has an explicit width/height rectangle (i.e. it
    takes the positioned path rather than the full-canvas path). Assumes
    ``validate_blend_geometry`` already accepted the layer."""
    return layer.blend != "normal" and layer.width is not None and layer.height is not None


def positioned_blend_chains(layer: Any, previous: str, layer_label: str) -> tuple[list[str], str]:
    """Build the positioned-blend filtergraph chains.

    Splits the running base into keep and crop-source streams, crops the latter
    to the layer rectangle, blends same-size with the scaled layer input, and
    overlays the blended tile onto the kept stream at the same position. All
    geometry is integral and validated; values are formatted as integers and
    escaped, never interpolated raw.

    Returns ``(extra_chains, overlay_step)`` where ``extra_chains`` carries the
    crop + blend chains and ``overlay_step`` is the final re-overlay (without the
    trailing output label, which the caller appends).
    """
    x = _escape_ffmpeg_filter_value(str(int(layer.position["x"])))
    y = _escape_ffmpeg_filter_value(str(int(layer.position["y"])))
    w = _escape_ffmpeg_filter_value(str(int(layer.width)))
    h = _escape_ffmpeg_filter_value(str(int(layer.height)))
    # Mode is resolved through the allowlist dict, never interpolated raw.
    mode = BLEND_ALL_MODES[layer.blend]
    keep_label = f"{layer_label}keep"
    crop_source_label = f"{layer_label}cropsource"
    crop_label = f"{layer_label}base"
    blend_label = f"{layer_label}blend"
    extra = [
        f"[{previous}]split=2[{keep_label}][{crop_source_label}]",
        f"[{crop_source_label}]crop={w}:{h}:{x}:{y}[{crop_label}]",
        f"[{crop_label}][{layer_label}]blend=all_mode={mode}[{blend_label}]",
    ]
    step = f"[{keep_label}][{blend_label}]overlay={x}:{y}:format=auto:eof_action=pass"
    return extra, step
