"""Rotation + pivot validation, filtergraph, and receipt helpers for composite-layers.

Split into its own module (like ``engine_composite_layers_blend.py``) to keep
``engine_composite_layers.py`` under the architecture guardrail's per-module
line limit (see
tests/test_architecture_guardrails.py::test_engine_modules_stay_below_project_size_limit).

Rotation composes with the OVERLAY (normal-blend) path only; a non-normal blend
layer with rotation/pivot is rejected by ``validate_blend_geometry`` (blend stays
full-canvas-only this release). Rotation combined with a mask/matte is deferred
and fails closed. Rotation degrees are validated as a finite float in
``[ROTATION_MIN, ROTATION_MAX]`` and formatted with bounded precision into a
radian literal — never interpolated raw.
"""

from __future__ import annotations

import math
from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _format_ffmpeg_number, _sanitize_ffmpeg_number

# Rotation is accepted in degrees within this inclusive range; anything outside
# fails closed. The plan (§6) leaves the numeric range open, so we bound it to a
# single full turn in each direction.
ROTATION_MIN = -360.0
ROTATION_MAX = 360.0

# Pivot value set (§6): the rotation origin AND the reference point that
# position{x,y} places for a rotated layer. Unknown pivots fail closed.
PIVOTS = ("center", "top_left", "top_right", "bottom_left", "bottom_right")
DEFAULT_PIVOT = "center"

# Overlay offset appended to position x/y per pivot when rotation is active. The
# offsets use the overlay input's own width/height (``w``/``h``), i.e. the
# rotated (expanded) layer dimensions, so the chosen reference point lands at
# position{x,y}. "top_left" keeps the historical top-left placement.
_PIVOT_X_OFFSET = {"center": "-w/2", "top_right": "-w", "bottom_right": "-w"}
_PIVOT_Y_OFFSET = {"center": "-h/2", "bottom_left": "-h", "bottom_right": "-h"}


def validate_rotation(layer: Any) -> float | None:
    """Validate and normalize ``layer.rotation`` (and its ``pivot``).

    Returns the rotation in degrees as a float, or ``None`` when rotation is
    unused. Fails closed on:

    * pivot supplied without rotation -> ``invalid_transform``;
    * non-numeric rotation -> ``unsupported_compositor_feature`` (§6);
    * out-of-range / non-finite rotation -> ``invalid_transform``;
    * rotation combined with a mask/matte -> ``unsupported_compositor_feature``
      (rotation + mask is deferred this release);
    * unknown pivot -> ``unsupported_compositor_feature`` (§6).
    """
    rotation = layer.rotation
    pivot = layer.pivot
    if rotation is None:
        if pivot is not None:
            raise MCPVideoError(
                f"layer {layer.id!r} sets pivot without rotation",
                error_type="validation_error",
                code="invalid_transform",
            )
        return None
    try:
        degrees = float(rotation)
    except (TypeError, ValueError):
        raise MCPVideoError(
            f"layer {layer.id!r} rotation must be a number of degrees",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        ) from None
    if not math.isfinite(degrees) or not (ROTATION_MIN <= degrees <= ROTATION_MAX):
        raise MCPVideoError(
            f"layer {layer.id!r} rotation must be a finite number of degrees within "
            f"[{ROTATION_MIN:g}, {ROTATION_MAX:g}]",
            error_type="validation_error",
            code="invalid_transform",
        )
    if layer.mask is not None or layer.matte is not None:
        raise MCPVideoError(
            f"layer {layer.id!r} combines rotation with a mask/matte; rotation + mask "
            "is deferred this release and fails closed",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        )
    effective_pivot = pivot if pivot is not None else DEFAULT_PIVOT
    if effective_pivot not in PIVOTS:
        raise MCPVideoError(
            f"layer {layer.id!r} pivot {pivot!r} is not supported; use one of {list(PIVOTS)}",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        )
    return degrees


def rotate_filter(rotation: float) -> str:
    """Transparent-fill rotate with an expanded bounding box.

    ``rotw``/``roth`` expand the output so the whole rotated layer fits, and
    ``fillcolor=none`` keeps the exposed corners alpha-transparent so the layer
    still composites cleanly. Degrees are converted to radians and formatted
    with bounded precision; the value is never interpolated raw.
    """
    radians = _fmt_num(math.radians(_sanitize_ffmpeg_number(rotation, "rotation")))
    safe = _escape_ffmpeg_filter_value(radians)
    return f"rotate={safe}:ow=rotw({safe}):oh=roth({safe}):fillcolor=none"


def overlay_position(layer: Any) -> tuple[str, str]:
    """Return the ``(x, y)`` overlay expressions for a layer.

    Without rotation this is the historical top-left placement of position
    x/y, so ``anchor``-as-position specs keep byte-identical filtergraphs. With
    rotation the pivot selects which reference point of the rotated (expanded)
    layer lands at position{x,y}, expressed against the overlay input's w/h.
    """
    x = _escape_ffmpeg_filter_value(_fmt_num(layer.position["x"]))
    y = _escape_ffmpeg_filter_value(_fmt_num(layer.position["y"]))
    if layer.rotation is None:
        return x, y
    pivot = layer.pivot or DEFAULT_PIVOT
    return f"{x}{_PIVOT_X_OFFSET.get(pivot, '')}", f"{y}{_PIVOT_Y_OFFSET.get(pivot, '')}"


def receipt_transform(layer: Any) -> dict[str, Any]:
    """layer_plan v2 transform block: size transform plus rotation + pivot.

    ``rotation``/``pivot`` are ``None`` when rotation is unused, matching the
    existing width/height/scale null-when-absent style.
    """
    rotation = layer.rotation
    pivot = (layer.pivot or DEFAULT_PIVOT) if rotation is not None else None
    return {
        "width": layer.width,
        "height": layer.height,
        "scale": layer.scale,
        "rotation": rotation,
        "pivot": pivot,
    }


def has_transform(layer: Any) -> bool:
    """True when a size transform (width/height/scale) is present. Rotation is
    tracked separately via ``features.rotation``."""
    return layer.width is not None or layer.height is not None or layer.scale is not None


# Shared FFmpeg number formatter (single source of truth in ffmpeg_helpers).
_fmt_num = _format_ffmpeg_number
