"""Input validation, types, and canonical intent/receipt payloads for graphics.

Split out of :mod:`kinocut.aivideo.graphics_recipe` so the facade stays under
the 800 LOC module ceiling. Layer types, validation, canvas normalization, the
receipt-safe layer form, the canonical parameter payload, the recipe-intent
hash, and the full receipt builder all live here. The render pipeline,
project-store interactions, and the public ``compose_graphics_recipe`` facade
stay in :mod:`kinocut.aivideo.graphics_recipe` and import from here.
"""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any

from pydantic import ConfigDict, Field, ValidationError, model_validator

from kinocut.contracts._common import ValueObject
from kinocut.defaults import (
    DEFAULT_FONT_SIZE,
    DEFAULT_GRAPHICS_CANVAS_BACKGROUND,
    DEFAULT_GRAPHICS_CANVAS_DURATION,
    DEFAULT_GRAPHICS_CANVAS_FPS,
    DEFAULT_GRAPHICS_LAYER_COLOR,
    DEFAULT_GRAPHICS_LAYER_OPACITY,
    DEFAULT_GRAPHICS_LAYER_POSITION_X,
    DEFAULT_GRAPHICS_LAYER_POSITION_Y,
    DEFAULT_HASH_CHUNK_BYTES,
)
from kinocut.engine_probe import probe
from kinocut.errors import MCPVideoError
from kinocut.limits import (
    MAX_GRAPHICS_CANVAS_DURATION,
    MAX_GRAPHICS_LAYERS,
    MAX_RESOLUTION,
)
from kinocut.validation import (
    GRAPHICS_GENERATIVE_FIELD_HINTS,
    GRAPHICS_HEX_COLOR_RE,
    GRAPHICS_LAYER_BASE_FIELDS,
)

# Stable receipt-protocol identifiers — point-of-use constants, not tunable
# defaults (the schema version pins the receipt format and never varies at
# runtime; the operation name is part of the receipt's content-addressed form).
_SCHEMA_VERSION = 1
_OPERATION_NAME = "graphics_recipe"
_PARAMETER_ERROR_CODE = "invalid_graphics_layer"


def _default_position() -> dict[str, float]:
    """Construct a fresh origin-position dict from immutable coordinate constants.

    Each call returns a brand-new dict so that no two GraphicsLayer instances
    ever alias the same position mapping. The underlying x/y values are the
    shared defaults from ``kinocut.defaults`` (immutable floats), eliminating
    mutable shared state while keeping the single-source-of-truth default.
    """

    return {
        "x": DEFAULT_GRAPHICS_LAYER_POSITION_X,
        "y": DEFAULT_GRAPHICS_LAYER_POSITION_Y,
    }


class GraphicsLayerKind(StrEnum):
    """The closed set of editor-layer kinds.

    Exact text/logos are deterministic editor layers — there is no ``ai_image``
    or ``generated`` kind and adding one would break the determinism guarantee.
    """

    TEXT = "text"
    LOGO = "logo"
    CAPTION = "caption"


class GraphicsLayer(ValueObject):
    """One normalized, deterministic editor layer."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    kind: GraphicsLayerKind
    text: str | None = None
    color: str = DEFAULT_GRAPHICS_LAYER_COLOR
    size: int = Field(default=DEFAULT_FONT_SIZE, gt=0)
    position: dict[str, float] = Field(default_factory=_default_position)
    start: float | None = None
    duration: float | None = None
    src: str | None = None
    opacity: float = DEFAULT_GRAPHICS_LAYER_OPACITY
    width: int | None = None
    height: int | None = None

    @model_validator(mode="after")
    def _kind_invariants(self) -> GraphicsLayer:
        if self.kind in (GraphicsLayerKind.TEXT, GraphicsLayerKind.CAPTION) and (
            self.text is None or not self.text.strip()
        ):
            raise ValueError(f"{self.kind.value} layer requires non-empty text")
        if self.kind is GraphicsLayerKind.LOGO and self.src is None:
            raise ValueError("logo layer requires src")
        if self.kind is GraphicsLayerKind.CAPTION:
            if self.start is None or self.duration is None:
                raise ValueError("caption layer requires start and duration")
            if self.start < 0 or self.duration <= 0:
                raise ValueError("caption timing must be non-negative start and positive duration")
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError("opacity must be between 0 and 1")
        return self


def _graphics_error(message: str, code: str) -> MCPVideoError:
    """Build a typed graphics error with a stable error_type/code pair."""

    type_map = {
        "graphics_source_changed": "integrity_error",
        "graphics_integrity_failed": "integrity_error",
    }
    return MCPVideoError(message, error_type=type_map.get(code, "validation_error"), code=code)


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode(
        "utf-8"
    )


def _digest(payload: bytes | dict[str, Any]) -> str:
    if isinstance(payload, dict):
        payload = _canonical(payload)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _sha256(path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(DEFAULT_HASH_CHUNK_BYTES), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _parse_position(raw: Any, offset: int) -> dict[str, float]:
    if raw is None:
        return _default_position()
    if not isinstance(raw, dict) or "x" not in raw or "y" not in raw:
        raise _graphics_error(f"layer {offset} position must have x and y", _PARAMETER_ERROR_CODE)
    try:
        return {"x": float(raw["x"]), "y": float(raw["y"])}
    except (TypeError, ValueError) as exc:
        raise _graphics_error(f"layer {offset} position is invalid", _PARAMETER_ERROR_CODE) from exc


def _validate_color(value: Any, offset: int) -> str:
    if not isinstance(value, str) or not GRAPHICS_HEX_COLOR_RE.fullmatch(value):
        raise _graphics_error(f"layer {offset} color must be a hex color like #FFFFFF", _PARAMETER_ERROR_CODE)
    return value if value.startswith("#") else f"#{value}"


def _validate_logo_src(src: str | None, offset: int) -> None:
    """Reject logo paths that smuggle non-local resources or traverse."""

    if not src or not src.strip():
        raise _graphics_error(f"layer {offset} logo src is empty", _PARAMETER_ERROR_CODE)
    if "://" in src or re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", src):
        raise _graphics_error(f"layer {offset} logo src must be a local file path", _PARAMETER_ERROR_CODE)
    if ".." in re.split(r"[\\/]+", src):
        raise _graphics_error(f"layer {offset} logo src must not traverse parent directories", _PARAMETER_ERROR_CODE)


def _validate_graphics_layer(raw: Any, offset: int) -> GraphicsLayer:
    if not isinstance(raw, dict):
        raise _graphics_error(f"layer {offset} must be an object", _PARAMETER_ERROR_CODE)
    if GRAPHICS_GENERATIVE_FIELD_HINTS & set(raw):
        raise _graphics_error(
            f"layer {offset} contains a forbidden generative field; exact text/logos are deterministic editor layers",
            _PARAMETER_ERROR_CODE,
        )
    unknown = set(raw) - GRAPHICS_LAYER_BASE_FIELDS
    if unknown:
        raise _graphics_error(f"layer {offset} uses unsupported field(s): {sorted(unknown)}", _PARAMETER_ERROR_CODE)
    try:
        kind = GraphicsLayerKind(raw.get("kind"))
    except (KeyError, ValueError) as exc:
        raise _graphics_error(f"layer {offset} has an unsupported kind", _PARAMETER_ERROR_CODE) from exc
    color = _validate_color(raw.get("color", DEFAULT_GRAPHICS_LAYER_COLOR), offset)
    position = _parse_position(raw.get("position"), offset)
    try:
        layer = GraphicsLayer(
            kind=kind,
            text=raw.get("text"),
            color=color,
            size=raw.get("size", DEFAULT_FONT_SIZE),
            position=position,
            start=raw.get("start"),
            duration=raw.get("duration"),
            src=raw.get("src"),
            opacity=raw.get("opacity", DEFAULT_GRAPHICS_LAYER_OPACITY),
            width=raw.get("width"),
            height=raw.get("height"),
        )
    except ValidationError as exc:
        raise _graphics_error(f"layer {offset} is invalid", _PARAMETER_ERROR_CODE) from exc
    if layer.kind is GraphicsLayerKind.LOGO:
        _validate_logo_src(layer.src, offset)
    return layer


def _validated_layers(layers: Any) -> list[GraphicsLayer]:
    if not isinstance(layers, list) or not layers:
        raise _graphics_error("layers must be a non-empty list", _PARAMETER_ERROR_CODE)
    if len(layers) > MAX_GRAPHICS_LAYERS:
        raise _graphics_error(f"layers must not exceed {MAX_GRAPHICS_LAYERS} entries", _PARAMETER_ERROR_CODE)
    return [_validate_graphics_layer(raw, i) for i, raw in enumerate(layers, start=1)]


def _normalized_canvas(raw: dict[str, Any] | None, source_path: str) -> dict[str, Any]:
    """Normalize the canvas dict; default to the background video dimensions."""

    if raw is None:
        info = probe(source_path)
        return {
            "width": int(info.width),
            "height": int(info.height),
            "fps": float(info.fps),
            "duration": min(float(info.duration), MAX_GRAPHICS_CANVAS_DURATION),
            "background": DEFAULT_GRAPHICS_CANVAS_BACKGROUND,
        }
    if not isinstance(raw, dict):
        raise _graphics_error("canvas must be an object", _PARAMETER_ERROR_CODE)
    width = raw.get("width")
    height = raw.get("height")
    if not isinstance(width, int) or width <= 0:
        raise _graphics_error("canvas.width must be a positive integer", _PARAMETER_ERROR_CODE)
    if not isinstance(height, int) or height <= 0:
        raise _graphics_error("canvas.height must be a positive integer", _PARAMETER_ERROR_CODE)
    if width > MAX_RESOLUTION or height > MAX_RESOLUTION:
        raise _graphics_error(f"canvas dimensions must not exceed {MAX_RESOLUTION}px", _PARAMETER_ERROR_CODE)
    fps = float(raw.get("fps", DEFAULT_GRAPHICS_CANVAS_FPS))
    duration = float(raw.get("duration", DEFAULT_GRAPHICS_CANVAS_DURATION))
    if fps <= 0:
        raise _graphics_error("canvas.fps must be positive", _PARAMETER_ERROR_CODE)
    if duration <= 0 or duration > MAX_GRAPHICS_CANVAS_DURATION:
        raise _graphics_error("canvas.duration is out of range", _PARAMETER_ERROR_CODE)
    background = raw.get("background", DEFAULT_GRAPHICS_CANVAS_BACKGROUND)
    if not isinstance(background, str) or not GRAPHICS_HEX_COLOR_RE.fullmatch(background):
        raise _graphics_error("canvas.background must be a hex color", _PARAMETER_ERROR_CODE)
    return {
        "width": int(width),
        "height": int(height),
        "fps": fps,
        "duration": duration,
        "background": background if background.startswith("#") else f"#{background}",
    }


def _receipt_layer(layer: GraphicsLayer, src_hash: str | None) -> dict[str, Any]:
    """Project-relative receipt-safe layer representation.

    Source paths are machine-specific; the receipt binds layers by their content
    hash (``src_hash`` for logos, ``layer_artifact_ids`` for text) so the receipt
    is deterministic across machines and never leaks absolute paths.
    """

    dump = layer.model_dump(mode="json")
    dump["src"] = None
    if src_hash is not None:
        dump["src_hash"] = src_hash
    return dump


def _parameter_payload(
    layers: list[GraphicsLayer],
    canvas: dict[str, Any],
    logo_hashes: dict[int, str],
) -> dict[str, Any]:
    """Canonical parameter shape; logo paths are replaced by their content hash."""

    entries: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        src_hash = logo_hashes.get(index) if layer.kind is GraphicsLayerKind.LOGO else None
        entries.append(_receipt_layer(layer, src_hash))
    return {"canvas": canvas, "layers": entries}


def _compute_intent(
    background_asset_id: str,
    font_hash: str,
    validated_layers: list[GraphicsLayer],
    canvas: dict[str, Any],
    logo_hashes: dict[int, str],
) -> tuple[str, str]:
    """Compute the canonical parameter + recipe hashes for the recipe."""

    parameter_hash = _digest(_parameter_payload(validated_layers, canvas, logo_hashes))
    recipe_hash = _digest(
        {
            "background_asset_id": background_asset_id,
            "font_hash": font_hash,
            "parameter_hash": parameter_hash,
        }
    )
    return parameter_hash, recipe_hash


def _build_layer_spec(index: int, layer: GraphicsLayer, src: str) -> dict[str, Any]:
    """Translate a graphics layer into one composite_layers image entry."""

    entry: dict[str, Any] = {
        "id": f"layer-{index}",
        "type": "image",
        "src": src,
        "opacity": layer.opacity,
        "position": layer.position,
    }
    if layer.kind is GraphicsLayerKind.CAPTION:
        entry["start"] = layer.start
        entry["duration"] = layer.duration
    if layer.kind is GraphicsLayerKind.LOGO and layer.width is not None and layer.height is not None:
        entry["width"] = layer.width
        entry["height"] = layer.height
    return entry


def _build_receipt_payload(
    *,
    background_asset_id: str,
    recipe_hash: str,
    parameter_hash: str,
    logo_hashes: dict[int, str],
    font_hash: str,
    output_hash: str,
    layer_artifact_ids: list[str],
    canvas: dict[str, Any],
    validated_layers: list[GraphicsLayer],
) -> dict[str, Any]:
    """Assemble the canonical receipt (without ``receipt_hash``; added by caller)."""

    return {
        "schema_version": _SCHEMA_VERSION,
        "operation": _OPERATION_NAME,
        "background_asset_id": background_asset_id,
        "recipe_hash": recipe_hash,
        "parameter_hash": parameter_hash,
        "source_asset_hashes": [background_asset_id, *logo_hashes.values()],
        "font_hash": font_hash,
        "output_hash": output_hash,
        "layer_artifact_ids": list(layer_artifact_ids),
        "canvas": canvas,
        "layers": [
            _receipt_layer(
                layer,
                logo_hashes.get(index) if layer.kind is GraphicsLayerKind.LOGO else None,
            )
            for index, layer in enumerate(validated_layers)
        ],
        "render_determinism_scope": (
            "input/recipe/font/output/receipt hashes are deterministic; "
            "rendered bytes may still vary across FFmpeg builds"
        ),
    }


def _verify_workspace_copies(
    background_copy,
    background_hash: str,
    font_copy,
    font_hash: str,
    logo_copies: dict[int, tuple[Any, str]],
    sha256,
) -> None:
    """Re-hash every workspace copy after render to fail closed on TOCTOU."""

    if sha256(background_copy) != background_hash:
        raise _graphics_error("background copy changed during render", "graphics_source_changed")
    if sha256(font_copy) != font_hash:
        raise _graphics_error("font copy changed during render", "graphics_source_changed")
    for logo_copy, logo_hash in logo_copies.values():
        if sha256(logo_copy) != logo_hash:
            raise _graphics_error("logo copy changed during render", "graphics_source_changed")
