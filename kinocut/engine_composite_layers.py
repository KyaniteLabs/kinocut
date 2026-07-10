"""Spec-driven multi-layer compositor."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .defaults import DEFAULT_CRF, DEFAULT_PRESET
from .engine_composite_layers_blend import BLEND_ALL_MODES, SUPPORTED_BLEND_MODES, validate_blend_geometry
from .engine_composite_layers_rotate import (
    has_transform, overlay_position, receipt_transform, rotate_filter, validate_rotation,
)
from .engine_composite_layers_source import _receipt_source, resolve_layer_source, resolve_mask_source
from .engine_runtime_utils import _timed_operation
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _format_ffmpeg_number,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .limits import MAX_RESOLUTION, MAX_VIDEO_DURATION
from .models import EditResult

_LAYER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
_SUPPORTED_LAYER_TYPES = {"video", "image", "solid"}
_UNSUPPORTED_TOP_LEVEL = {"passes"}
_SUPPORTED_LAYER_FIELDS = {
    "anchor",
    "blend",
    "color",
    "duration",
    "height",
    "id",
    "mask",
    "matte",
    "opacity",
    "pivot",
    "position",
    "rotation",
    "scale",
    "src",
    "start",
    "transform",
    "type",
    "width",
    "x",
    "y",
}
_IMAGE_OUTPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_IMAGE_INPUT_SUFFIXES = _IMAGE_OUTPUT_SUFFIXES


class CompositeLayerResult(EditResult):
    """Result for composite-layers including the deterministic receipt."""

    layer_plan_path: str | None = None
    layer_plan: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False


class _Canvas(BaseModel):
    width: int
    height: int
    fps: float = 24.0
    duration: float = 2.0
    background: str = "#000000"


class _Layer(BaseModel):
    id: str
    type: Literal["video", "image", "solid"]
    opacity: float = 1.0
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    width: int | None = None
    height: int | None = None
    scale: float | None = None
    rotation: Any = None
    pivot: str | None = None
    start: float | None = None
    duration: float | None = None
    src: str | None = None
    mask: str | None = None
    matte: str | None = None
    color: str | None = None
    blend: str = "normal"


class _ResolvedLayer(BaseModel):
    id: str
    type: Literal["video", "image", "solid"]
    opacity: float
    position: dict[str, float]
    width: int | None = None
    height: int | None = None
    scale: float | None = None
    rotation: float | None = None
    pivot: str | None = None
    start: float | None = None
    duration: float | None = None
    src: str | None = None
    resolved_src: str | None = None
    mask_src: str | None = None
    resolved_mask_src: str | None = None
    color: str | None = None
    blend: str = "normal"
    input_index: int
    mask_input_index: int | None = None


def composite_layers(
    spec_path: str,
    output_path: str | None = None,
    save_layer_plan: str | None = None,
    dry_run: bool = False,
) -> CompositeLayerResult:
    """Render an ordered layer stack from a JSON spec.

    The compositor supports normal alpha compositing, per-layer opacity,
    x/y positioning, scale/width/height transforms, timeline enable windows,
    image/video/solid layers, optional mask/matte alpha sources, full-canvas
    non-normal blend modes (see ``validate_blend_geometry``), transparent-fill
    rotation with a ``pivot`` reference point (see
    ``engine_composite_layers_rotate``), and a deterministic layer-plan receipt.
    Per-layer effect routing, positioned/masked blend, and rotation combined
    with a mask remain deferred and fail closed.
    """
    spec_resolved = _validate_spec_path(spec_path)
    spec_data, spec_bytes = _load_spec(spec_resolved)
    canvas = _parse_canvas(spec_data.get("canvas"))
    layers = _parse_layers(spec_data, spec_resolved.parent)
    output = _resolve_output_path(output_path, spec_resolved, spec_data)
    layer_plan_output = _resolve_layer_plan_path(save_layer_plan, output)

    filter_complex = _build_filter_complex(canvas, layers)
    args = _build_ffmpeg_args(canvas, layers, filter_complex, output)
    receipt = _build_layer_plan(spec_bytes, canvas, layers, filter_complex, output, spec_resolved.parent)

    if dry_run:
        timing: dict[str, float | None] = {"elapsed_ms": None}
    else:
        with _timed_operation() as timing:
            _run_ffmpeg(args)
        receipt["output_hash"] = _file_hash(output)

    if layer_plan_output is not None:
        Path(layer_plan_output).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    return _build_composite_result(output, timing, receipt, layer_plan_output, dry_run=dry_run)


def _validate_spec_path(spec_path: str) -> Path:
    if "\x00" in spec_path:
        raise MCPVideoError(
            "spec path contains null bytes",
            error_type="validation_error",
            code="invalid_spec_path",
        )
    resolved = Path(_validate_input_path(spec_path)).resolve()
    if resolved.suffix.lower() != ".json":
        raise MCPVideoError(
            "composite-layers spec must be a JSON file",
            error_type="validation_error",
            code="invalid_spec_path",
        )
    return resolved


def _load_spec(spec_path: Path) -> tuple[dict[str, Any], bytes]:
    raw = spec_path.read_bytes()
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise MCPVideoError(
            f"invalid composite-layers JSON: {exc.msg}",
            error_type="validation_error",
            code="invalid_spec_json",
        ) from None
    if not isinstance(data, dict):
        raise MCPVideoError(
            "composite-layers spec must be a JSON object",
            error_type="validation_error",
            code="invalid_spec",
        )
    return data, raw


def _parse_canvas(raw_canvas: Any) -> _Canvas:
    if not isinstance(raw_canvas, dict):
        raise MCPVideoError("canvas must be an object", error_type="validation_error", code="invalid_spec")
    data = dict(raw_canvas)
    data["width"] = data.pop("width", data.pop("w", None))
    data["height"] = data.pop("height", data.pop("h", None))
    data["background"] = data.pop("background", data.pop("bg", "#000000"))
    try:
        canvas = _Canvas(**data)
    except Exception as exc:
        raise MCPVideoError(
            f"invalid canvas: {exc}",
            error_type="validation_error",
            code="invalid_canvas",
        ) from None
    _positive_int(canvas.width, "canvas.width")
    _positive_int(canvas.height, "canvas.height")
    _positive_number(canvas.fps, "canvas.fps")
    _positive_number(canvas.duration, "canvas.duration")
    # Clamp canvas dimensions/duration so an over-large spec cannot fan out into a
    # multi-gigapixel / multi-hour FFmpeg job (DoS). Bounds match the shared limits.
    if canvas.width > MAX_RESOLUTION or canvas.height > MAX_RESOLUTION:
        raise MCPVideoError(
            f"canvas dimensions must not exceed {MAX_RESOLUTION}px",
            error_type="validation_error",
            code="invalid_canvas",
        )
    if canvas.duration > MAX_VIDEO_DURATION:
        raise MCPVideoError(
            f"canvas.duration must not exceed {MAX_VIDEO_DURATION} seconds",
            error_type="validation_error",
            code="invalid_canvas",
        )
    _validate_color(canvas.background, "canvas.background")
    return canvas


def _parse_layers(spec_data: dict[str, Any], spec_dir: Path) -> list[_ResolvedLayer]:
    unsupported = sorted(_UNSUPPORTED_TOP_LEVEL & set(spec_data))
    if unsupported:
        raise MCPVideoError(
            f"unsupported composite-layers field(s): {unsupported}",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        )
    raw_layers = spec_data.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise MCPVideoError("layers must be a non-empty list", error_type="validation_error", code="invalid_layers")
    seen: set[str] = set()
    resolved: list[_ResolvedLayer] = []
    input_index = 1
    for offset, raw in enumerate(raw_layers, start=1):
        if not isinstance(raw, dict):
            raise MCPVideoError("each layer must be an object", error_type="validation_error", code="invalid_layer")
        _reject_unknown_layer_fields(raw, offset)
        layer = _parse_layer(raw)
        if layer.id in seen:
            raise MCPVideoError(
                f"duplicate layer id: {layer.id}",
                error_type="validation_error",
                code="duplicate_layer_id",
            )
        seen.add(layer.id)
        src, receipt_src = resolve_layer_source(layer, spec_dir)
        mask_src, receipt_mask_src = resolve_mask_source(layer, spec_dir)
        mask_input_index = input_index + 1 if mask_src is not None else None
        resolved.append(
            _ResolvedLayer(
                id=layer.id,
                type=layer.type,
                opacity=layer.opacity,
                position=layer.position,
                width=layer.width,
                height=layer.height,
                scale=layer.scale,
                rotation=layer.rotation,
                pivot=layer.pivot,
                start=layer.start,
                duration=layer.duration,
                src=src,
                resolved_src=receipt_src,
                mask_src=mask_src,
                resolved_mask_src=receipt_mask_src,
                color=layer.color,
                blend=layer.blend,
                input_index=input_index,
                mask_input_index=mask_input_index,
            )
        )
        input_index += 2 if mask_src is not None else 1
    return resolved


def _reject_unknown_layer_fields(raw: dict[str, Any], offset: int) -> None:
    unsupported = sorted(set(raw) - _SUPPORTED_LAYER_FIELDS)
    if unsupported:
        raise MCPVideoError(
            f"layer {raw.get('id', offset)!r} uses unsupported field(s): {unsupported}",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        )


def _parse_layer(raw: dict[str, Any]) -> _Layer:
    data = dict(raw)
    data["position"] = _extract_position(data)
    try:
        layer = _Layer(**data)
    except Exception as exc:
        raise MCPVideoError(
            f"invalid layer: {exc}",
            error_type="validation_error",
            code="invalid_layer",
        ) from None
    if not _LAYER_ID_RE.fullmatch(layer.id):
        raise MCPVideoError(
            f"layer id must match {_LAYER_ID_RE.pattern}: {layer.id!r}",
            error_type="validation_error",
            code="invalid_layer_id",
        )
    if layer.type not in _SUPPORTED_LAYER_TYPES:
        raise MCPVideoError(
            f"unsupported layer type: {layer.type}",
            error_type="validation_error",
            code="invalid_layer_type",
        )
    if layer.blend != "normal" and layer.blend not in BLEND_ALL_MODES:
        raise MCPVideoError(
            f"blend mode {layer.blend!r} is not supported; use one of {sorted(SUPPORTED_BLEND_MODES)}",
            error_type="validation_error",
            code="unsupported_blend_mode",
        )
    _validate_opacity(layer.opacity, layer.id)
    _non_negative_number(layer.position["x"], f"{layer.id}.position.x")
    _non_negative_number(layer.position["y"], f"{layer.id}.position.y")
    _validate_layer_transform(layer)
    _validate_layer_timing(layer)
    layer.rotation = validate_rotation(layer)
    if layer.blend != "normal":
        validate_blend_geometry(layer)
    if layer.type == "solid":
        layer.color = _validate_color(layer.color or "#000000", f"{layer.id}.color")
    elif not layer.src:
        raise MCPVideoError(
            f"layer {layer.id!r} requires src",
            error_type="validation_error",
            code="missing_layer_src",
        )
    return layer


def _extract_position(data: dict[str, Any]) -> dict[str, float]:
    raw = data.pop("position", None)
    if raw is None:
        raw = data.pop("anchor", None)
    transform = data.pop("transform", None)
    if transform is not None and not isinstance(transform, dict):
        raise MCPVideoError("transform must be an object", error_type="validation_error", code="invalid_transform")
    if isinstance(transform, dict):
        unsupported = {k for k in transform if k not in {"x", "y", "width", "height", "scale"}}
        if unsupported:
            raise MCPVideoError(
                f"transform field(s) {sorted(unsupported)} are deferred beyond P2",
                error_type="validation_error",
                code="unsupported_compositor_feature",
            )
        for key in ("width", "height", "scale"):
            if key in transform and key not in data:
                data[key] = transform[key]
    if raw is None and isinstance(transform, dict):
        raw = transform
    if raw is None:
        raw = {"x": data.pop("x", 0), "y": data.pop("y", 0)}
    if not isinstance(raw, dict):
        raise MCPVideoError("position must be an object", error_type="validation_error", code="invalid_position")
    try:
        return {"x": float(raw.get("x", 0)), "y": float(raw.get("y", 0))}
    except (TypeError, ValueError) as exc:
        raise MCPVideoError(
            f"position x/y values must be numeric: {exc}",
            error_type="validation_error",
            code="invalid_position",
        ) from None


def _validate_layer_transform(layer: _Layer) -> None:
    if layer.scale is not None and (layer.width is not None or layer.height is not None):
        raise MCPVideoError(
            f"layer {layer.id!r} cannot combine scale with width/height",
            error_type="validation_error",
            code="invalid_transform",
        )
    if layer.width is not None:
        _positive_int(layer.width, f"{layer.id}.width")
    if layer.height is not None:
        _positive_int(layer.height, f"{layer.id}.height")
    if layer.scale is not None:
        _positive_number(layer.scale, f"{layer.id}.scale")


def _validate_layer_timing(layer: _Layer) -> None:
    if layer.start is not None:
        _non_negative_number(layer.start, f"{layer.id}.start")
    if layer.duration is not None:
        _positive_number(layer.duration, f"{layer.id}.duration")
    if layer.duration is not None and layer.start is None:
        raise MCPVideoError(
            f"layer {layer.id!r} duration requires start",
            error_type="validation_error",
            code="invalid_layer_timing",
        )


def _resolve_output_path(output_path: str | None, spec_path: Path, spec_data: dict[str, Any]) -> str:
    if output_path is None:
        output_obj = spec_data.get("output")
        if isinstance(output_obj, dict) and output_obj.get("path"):
            output_path = str(output_obj["path"])
        else:
            fmt = "mp4"
            if isinstance(output_obj, dict) and output_obj.get("format"):
                fmt = str(output_obj["format"]).lstrip(".")
            output_path = str(spec_path.with_name(f"{spec_path.stem}_composite.{fmt}"))
    if not Path(output_path).is_absolute():
        output_path = str(spec_path.parent / output_path)
    _validate_output_path(output_path)
    return output_path


def _resolve_layer_plan_path(save_layer_plan: str | None, output_path: str) -> str | None:
    if save_layer_plan is None:
        return None
    path = save_layer_plan
    if not Path(path).is_absolute():
        path = str(Path(output_path).parent / path)
    _validate_output_path(path)
    return path


def _build_ffmpeg_args(
    canvas: _Canvas, layers: list[_ResolvedLayer], filter_complex: str, output_path: str
) -> list[str]:
    args: list[str] = [
        "-f",
        "lavfi",
        "-t",
        _num(canvas.duration),
        "-r",
        _num(canvas.fps),
        "-i",
        _canvas_filter(canvas),
    ]
    for layer in layers:
        if layer.type == "image":
            if layer.src is None:
                raise MCPVideoError("image layer missing src", error_type="validation_error", code="missing_layer_src")
            args.extend(["-loop", "1", "-t", _num(canvas.duration), "-i", layer.src])
        elif layer.type == "video":
            if layer.src is None:
                raise MCPVideoError("video layer missing src", error_type="validation_error", code="missing_layer_src")
            args.extend(["-i", layer.src])
        else:
            args.extend(["-f", "lavfi", "-t", _num(canvas.duration), "-i", _solid_filter(layer, canvas)])
        if layer.mask_src is not None:
            if _is_image_path(layer.mask_src):
                args.extend(["-loop", "1", "-t", _num(canvas.duration), "-i", layer.mask_src])
            else:
                args.extend(["-i", layer.mask_src])
    image_output = Path(output_path).suffix.lower() in _IMAGE_OUTPUT_SUFFIXES
    args.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-an"])
    if image_output:
        args.extend(["-frames:v", "1", "-update", "1"])
    else:
        args.extend(
            [
                "-t",
                _num(canvas.duration),
                "-c:v",
                "libx264",
                "-preset",
                DEFAULT_PRESET,
                "-crf",
                str(DEFAULT_CRF),
                "-pix_fmt",
                "yuv420p",
            ]
        )
    args.append(output_path)
    return args


def _build_filter_complex(canvas: _Canvas, layers: list[_ResolvedLayer]) -> str:
    chains = ["[0:v]format=rgba[base0]"]
    previous = "base0"
    for idx, layer in enumerate(layers, start=1):
        layer_label = f"layer{idx}"
        out_label = "vout" if idx == len(layers) else f"base{idx}"
        chain = _layer_filter_chain(layer)
        if layer.blend != "normal":
            # Full-canvas only (validated in _validate_blend_geometry). blend=
            # requires matching-size inputs, so force the source to canvas size.
            width = _escape_ffmpeg_filter_value(str(canvas.width))
            height = _escape_ffmpeg_filter_value(str(canvas.height))
            chain = f"{chain},scale={width}:{height}"
        chains.append(f"[{layer.input_index}:v]{chain}[{layer_label}raw]")
        if layer.mask_input_index is not None:
            mask_label = f"{layer_label}mask"
            layer_ref_label = f"{layer_label}ref"
            chains.append(f"[{layer.mask_input_index}:v]format=gray[{mask_label}raw]")
            # Bare scale2ref scales the mask to the layer size on all FFmpeg
            # versions; the rw/rh form only parses on FFmpeg 7+ (breaks FFmpeg 6).
            chains.append(
                f"[{mask_label}raw][{layer_label}raw]scale2ref[{mask_label}][{layer_ref_label}]"
            )
            chains.append(f"[{layer_ref_label}][{mask_label}]alphamerge[{layer_label}]")
        else:
            chains.append(f"[{layer_label}raw]null[{layer_label}]")
        if layer.blend == "normal":
            x, y = overlay_position(layer)
            step = f"[{previous}][{layer_label}]overlay={x}:{y}:format=auto:eof_action=pass"
            step = f"{step}{_enable_expression(layer)}"
        else:
            # Mode is resolved through the allowlist dict, never interpolated from
            # the raw spec value.
            step = f"[{previous}][{layer_label}]blend=all_mode={BLEND_ALL_MODES[layer.blend]}"
        step = f"{step},format=yuv420p[{out_label}]" if idx == len(layers) else f"{step}[{out_label}]"
        chains.append(step)
        previous = out_label
    return ";".join(chains)


def _layer_filter_chain(layer: _ResolvedLayer) -> str:
    parts = ["format=rgba"]
    scale_filter = _scale_filter(layer)
    if scale_filter is not None:
        parts.append(scale_filter)
    if layer.rotation is not None:
        parts.append(rotate_filter(layer.rotation))
    opacity = _escape_ffmpeg_filter_value(f"{_validate_opacity(layer.opacity, layer.id):.2f}")
    parts.append(f"colorchannelmixer=aa={opacity}")
    return ",".join(parts)


def _scale_filter(layer: _ResolvedLayer) -> str | None:
    if layer.scale is not None:
        scale = _escape_ffmpeg_filter_value(_num(layer.scale))
        return f"scale=iw*{scale}:ih*{scale}"
    if layer.width is None and layer.height is None:
        return None
    width = _escape_ffmpeg_filter_value(_num(layer.width)) if layer.width is not None else "-1"
    height = _escape_ffmpeg_filter_value(_num(layer.height)) if layer.height is not None else "-1"
    return f"scale={width}:{height}"


def _enable_expression(layer: _ResolvedLayer) -> str:
    if layer.start is None:
        return ""
    safe_start = _escape_ffmpeg_filter_value(_num(layer.start))
    if layer.duration is None:
        return f":enable='gte(t\\,{safe_start})'"
    safe_end = _escape_ffmpeg_filter_value(_num(layer.start + layer.duration))
    return f":enable='between(t\\,{safe_start}\\,{safe_end})'"


def _build_layer_plan(
    spec_bytes: bytes,
    canvas: _Canvas,
    layers: list[_ResolvedLayer],
    filter_complex: str,
    output_path: str,
    spec_dir: Path,
) -> dict[str, Any]:
    summary = [
        "canvas normalized to rgba",
        "layers transformed and overlaid bottom-to-top with normal alpha compositing",
        "per-layer opacity applied via colorchannelmixer alpha",
        "mask/matte inputs are scaled to the transformed layer and applied as alpha with alphamerge",
        "start/duration windows are enforced with overlay enable expressions",
    ]
    if any(layer.blend != "normal" for layer in layers):
        summary.append("full-canvas non-normal blend layers use blend=all_mode against the running base")
    if any(layer.rotation is not None for layer in layers):
        summary.append("rotated layers use transparent-fill rotate (scale -> rotate -> opacity -> position); pivot sets the reference point")
    return {
        "schema_version": 2,
        "receipt_kind": "layer_plan",
        "tool": "video_composite_layers",
        "spec_hash": "sha256:" + hashlib.sha256(spec_bytes).hexdigest(),
        "canvas": canvas.model_dump(),
        "layers": [
            {
                "id": layer.id,
                "type": layer.type,
                "resolved_src": layer.resolved_src,
                "source_hash": _file_hash(layer.src),
                "opacity": layer.opacity,
                "position": layer.position,
                "transform": receipt_transform(layer),
                "timing": _receipt_timing(layer),
                "mask": layer.resolved_mask_src,
                "mask_hash": _file_hash(layer.mask_src),
                "blend": layer.blend,
                "color": layer.color,
                "input_index": layer.input_index,
                "mask_input_index": layer.mask_input_index,
            }
            for layer in layers
        ],
        "filtergraph_summary": summary,
        "filtergraph_hash": "sha256:" + hashlib.sha256(filter_complex.encode("utf-8")).hexdigest(),
        "output_path": _receipt_source(Path(output_path), spec_dir),
        "output_hash": None,
        "audio_policy": "dropped_video_only",
        "features": {
            "layer_types": sorted({layer.type for layer in layers}),
            "transforms": any(has_transform(layer) for layer in layers),
            "rotation": any(layer.rotation is not None for layer in layers),
            "timing_windows": any(layer.start is not None for layer in layers),
            "masks": any(layer.mask_src is not None for layer in layers),
            "blend_modes": sorted({layer.blend for layer in layers}),
            "audio": "dropped",
        },
        "render_determinism_scope": (
            "input/spec/filtergraph/output hashes are deterministic; rendered bytes may still vary across FFmpeg builds"
        ),
    }


def _build_composite_result(
    output_path: str,
    timing: dict[str, float | None],
    receipt: dict[str, Any],
    layer_plan_path: str | None,
    *,
    dry_run: bool = False,
) -> CompositeLayerResult:
    if dry_run:
        return CompositeLayerResult(
            output_path=output_path,
            operation="composite_layers_dry_run",
            format=Path(output_path).suffix.lower().lstrip("."),
            elapsed_ms=timing["elapsed_ms"],
            layer_plan_path=layer_plan_path,
            layer_plan=receipt,
            dry_run=True,
        )
    if Path(output_path).suffix.lower() in _IMAGE_OUTPUT_SUFFIXES:
        return CompositeLayerResult(
            output_path=output_path,
            operation="composite_layers",
            format=Path(output_path).suffix.lower().lstrip("."),
            elapsed_ms=timing["elapsed_ms"],
            layer_plan_path=layer_plan_path,
            layer_plan=receipt,
            dry_run=False,
        )
    from .engine_probe import probe

    info = probe(output_path)
    return CompositeLayerResult(
        output_path=output_path,
        duration=info.duration,
        resolution=info.resolution,
        size_mb=info.size_mb,
        format=info.format or Path(output_path).suffix.lower().lstrip("."),
        operation="composite_layers",
        elapsed_ms=timing["elapsed_ms"],
        layer_plan_path=layer_plan_path,
        layer_plan=receipt,
        dry_run=False,
    )


def _receipt_timing(layer: _ResolvedLayer) -> dict[str, float | None]:
    return {"start": layer.start, "duration": layer.duration}


def _canvas_filter(canvas: _Canvas) -> str:
    color = _escape_ffmpeg_filter_value(_ffmpeg_color(canvas.background))
    return f"color=c={color}:s={canvas.width}x{canvas.height}:d={_num(canvas.duration)}"


def _solid_filter(layer: _ResolvedLayer, canvas: _Canvas) -> str:
    color = _escape_ffmpeg_filter_value(_ffmpeg_color(layer.color or "#000000"))
    return f"color=c={color}:s={canvas.width}x{canvas.height}:d={_num(canvas.duration)}"


def _validate_color(value: str, name: str) -> str:
    if not isinstance(value, str) or not _HEX_COLOR_RE.fullmatch(value):
        raise MCPVideoError(
            f"{name} must be a hex color like #000000",
            error_type="validation_error",
            code="invalid_color",
        )
    return value if value.startswith("#") else f"#{value}"


def _ffmpeg_color(value: str) -> str:
    return "0x" + value.lstrip("#")


def _validate_opacity(value: float, layer_id: str) -> float:
    opacity = _sanitize_ffmpeg_number(value, f"{layer_id}.opacity")
    if not 0.0 <= opacity <= 1.0:
        raise MCPVideoError(
            f"{layer_id}.opacity must be between 0 and 1",
            error_type="validation_error",
            code="invalid_opacity",
        )
    return opacity


def _positive_int(value: int, name: str) -> None:
    if not isinstance(value, int) or value <= 0:
        raise MCPVideoError(
            f"{name} must be a positive integer", error_type="validation_error", code="invalid_parameter"
        )


def _positive_number(value: float, name: str) -> None:
    number = _sanitize_ffmpeg_number(value, name)
    if number <= 0:
        raise MCPVideoError(f"{name} must be positive", error_type="validation_error", code="invalid_parameter")


def _non_negative_number(value: float, name: str) -> None:
    number = _sanitize_ffmpeg_number(value, name)
    if number < 0:
        raise MCPVideoError(f"{name} must be non-negative", error_type="validation_error", code="invalid_parameter")


# Shared FFmpeg number formatter (single source of truth in ffmpeg_helpers).
_num = _format_ffmpeg_number


def _is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_INPUT_SUFFIXES


def _file_hash(path: str | None) -> str | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()
