"""Validated per-layer effect routing for ``composite-layers``."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from .defaults import (
    DEFAULT_COMPOSITOR_NOISE_ANIMATED,
    DEFAULT_COMPOSITOR_NOISE_INTENSITY,
    DEFAULT_COMPOSITOR_NOISE_MODE,
)
from .errors import MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _format_ffmpeg_number
from .validation import COMPOSITOR_EFFECT_NOISE_MODES, COMPOSITOR_EFFECT_REGIONS, COMPOSITOR_EFFECTS

_TARGET_RE = re.compile(r"^layer:([A-Za-z0-9_-]+)(?:\.(mask(?:\.edge)?))?$")
_PASS_FIELDS = frozenset({"effect", "args", "target"})
_NOISE_ARG_FIELDS = frozenset({"animated", "intensity", "mode"})


@dataclass(frozen=True)
class RoutedEffect:
    """One normalized effect pass bound to a validated layer stream."""

    effect: str
    target: str
    layer_id: str
    region: str
    args: dict[str, Any]
    order: int


def attach_effect_passes(raw_passes: Any, layers: list[Any]) -> list[Any]:
    """Validate passes and attach them to immutable per-layer tuples."""
    if raw_passes is None:
        return layers
    if not isinstance(raw_passes, list):
        raise _route_error("passes must be a list", "invalid_effect_route")

    by_id = {layer.id: layer for layer in layers}
    routed: dict[str, list[RoutedEffect]] = {layer.id: [] for layer in layers}
    for offset, raw in enumerate(raw_passes, start=1):
        effect = _parse_pass(raw, offset, by_id)
        routed[effect.layer_id].append(effect)
    return [layer.model_copy(update={"effects": tuple(routed[layer.id])}) for layer in layers]


def effect_filters(layer: Any, region: str) -> list[str]:
    """Return allowlisted FFmpeg filters for one validated route region."""
    filters: list[str] = []
    for effect in layer.effects:
        if effect.region == region:
            filters.append(_noise_filter(effect))
    return filters


def mask_effect_chains(layer: Any, input_label: str, output_label: str) -> list[str]:
    """Apply mask and mask-edge routes while preserving the original mask."""
    chains: list[str] = []
    current = input_label
    mask_filters = effect_filters(layer, "mask")
    if mask_filters:
        routed = f"{output_label}direct"
        chains.append(f"[{current}]{','.join(mask_filters)}[{routed}]")
        current = routed

    edge_filters = effect_filters(layer, "mask.edge")
    if edge_filters:
        base = f"{output_label}base"
        edge_source = f"{output_label}edgesource"
        edge = f"{output_label}edge"
        chains.append(f"[{current}]split=2[{base}][{edge_source}]")
        edge_chain = ",".join(["edgedetect=mode=colormix", *edge_filters])
        chains.append(f"[{edge_source}]{edge_chain}[{edge}]")
        chains.append(f"[{base}][{edge}]blend=all_mode=screen[{output_label}]")
    elif current != output_label:
        chains.append(f"[{current}]null[{output_label}]")
    else:
        chains.append(f"[{current}]null[{output_label}]")
    return chains


def effect_route_receipts(layers: list[Any]) -> list[dict[str, Any]]:
    """Return deterministic, public-safe route decisions in spec order."""
    return [
        {"effect": effect.effect, "target": effect.target, "args": dict(effect.args)}
        for effect in sorted(
            (effect for layer in layers for effect in layer.effects),
            key=lambda item: item.order,
        )
    ]


def _parse_pass(raw: Any, offset: int, layers: dict[str, Any]) -> RoutedEffect:
    if not isinstance(raw, dict):
        raise _route_error(f"pass {offset} must be an object", "invalid_effect_route")
    unknown = sorted(set(raw) - _PASS_FIELDS)
    if unknown:
        raise _route_error(f"pass {offset} uses unsupported field(s): {unknown}", "unsupported_effect_route")

    effect = raw.get("effect")
    if effect not in COMPOSITOR_EFFECTS:
        raise _route_error(
            f"pass {offset} effect {effect!r} is unsupported; use one of {sorted(COMPOSITOR_EFFECTS)}",
            "unsupported_effect_route",
        )
    target = raw.get("target")
    if not isinstance(target, str):
        raise _route_error(f"pass {offset} target must be a route string", "invalid_effect_route")
    match = _TARGET_RE.fullmatch(target)
    if match is None:
        raise _route_error(
            f"pass {offset} target must use layer:<id>, layer:<id>.mask, or layer:<id>.mask.edge",
            "invalid_effect_route",
        )
    layer_id = match.group(1)
    region = match.group(2) or "layer"
    if region not in COMPOSITOR_EFFECT_REGIONS:
        raise _route_error(f"pass {offset} route region is unsupported", "unsupported_effect_route")
    layer = layers.get(layer_id)
    if layer is None:
        raise _route_error(f"pass {offset} targets unknown layer {layer_id!r}", "unknown_effect_target")
    if region != "layer" and layer.mask_src is None:
        raise _route_error(f"pass {offset} targets {target!r}, but that layer has no mask/matte", "missing_effect_mask")

    args = _parse_noise_args(raw.get("args", {}), offset)
    return RoutedEffect(effect=effect, target=target, layer_id=layer_id, region=region, args=args, order=offset)


def _parse_noise_args(raw: Any, offset: int) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise _route_error(f"pass {offset} args must be an object", "invalid_effect_route")
    unknown = sorted(set(raw) - _NOISE_ARG_FIELDS)
    if unknown:
        raise _route_error(f"pass {offset} uses unsupported effect arg(s): {unknown}", "unsupported_effect_route")

    intensity = raw.get("intensity", DEFAULT_COMPOSITOR_NOISE_INTENSITY)
    if isinstance(intensity, bool) or not isinstance(intensity, (int, float)) or not math.isfinite(float(intensity)):
        raise _route_error(f"pass {offset} noise intensity must be a finite number", "invalid_effect_parameter")
    intensity = float(intensity)
    if not 0.0 <= intensity <= 1.0:
        raise _route_error(f"pass {offset} noise intensity must be between 0 and 1", "invalid_effect_parameter")

    mode = raw.get("mode", DEFAULT_COMPOSITOR_NOISE_MODE)
    if mode not in COMPOSITOR_EFFECT_NOISE_MODES:
        raise _route_error(
            f"pass {offset} noise mode must be one of {sorted(COMPOSITOR_EFFECT_NOISE_MODES)}",
            "invalid_effect_parameter",
        )
    animated = raw.get("animated", DEFAULT_COMPOSITOR_NOISE_ANIMATED)
    if not isinstance(animated, bool):
        raise _route_error(f"pass {offset} noise animated must be boolean", "invalid_effect_parameter")
    return {"animated": animated, "intensity": intensity, "mode": mode}


def _noise_filter(effect: RoutedEffect) -> str:
    strength = _escape_ffmpeg_filter_value(_format_ffmpeg_number(effect.args["intensity"] * 100.0))
    flags = "t+u" if effect.args["animated"] else "u"
    channel = "alls" if effect.args["mode"] == "color" else "c0s"
    return f"noise={channel}={strength}:{channel[:-1]}f={flags}"


def _route_error(message: str, code: str) -> MCPVideoError:
    return MCPVideoError(message, error_type="validation_error", code=code)
