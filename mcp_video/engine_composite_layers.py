"""Spec-driven multi-layer compositor P1."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from .engine_runtime_utils import _timed_operation
from .errors import MCPVideoError
from .ffmpeg_helpers import (
    _escape_ffmpeg_filter_value,
    _run_ffmpeg,
    _sanitize_ffmpeg_number,
    _validate_input_path,
    _validate_output_path,
)
from .models import EditResult

_LAYER_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_HEX_COLOR_RE = re.compile(r"^#?[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
_SUPPORTED_LAYER_TYPES = {"video", "image", "solid"}
_P1_UNSUPPORTED_TOP_LEVEL = {"passes"}
_P1_UNSUPPORTED_LAYER_FIELDS = {"mask", "matte"}
_IMAGE_OUTPUT_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class CompositeLayerResult(EditResult):
    """Result for composite-layers including the deterministic P1 receipt."""

    layer_plan_path: str | None = None
    layer_plan: dict[str, Any] = Field(default_factory=dict)


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
    src: str | None = None
    color: str | None = None
    blend: str = "normal"


class _ResolvedLayer(BaseModel):
    id: str
    type: Literal["video", "image", "solid"]
    opacity: float
    position: dict[str, float]
    src: str | None = None
    resolved_src: str | None = None
    color: str | None = None
    blend: str = "normal"
    input_index: int


def composite_layers(
    spec_path: str,
    output_path: str | None = None,
    save_layer_plan: str | None = None,
) -> CompositeLayerResult:
    """Render a P1 ordered layer stack from a JSON spec.

    P1 supports normal alpha compositing, per-layer opacity, fixed x/y
    positioning, image/video/solid layers, and a deterministic layer-plan
    receipt. Masks, non-normal blend modes, scale/rotate transforms, and
    per-layer effects are intentionally deferred to later phases.
    """
    spec_resolved = _validate_spec_path(spec_path)
    spec_data, spec_bytes = _load_spec(spec_resolved)
    canvas = _parse_canvas(spec_data.get("canvas"))
    layers = _parse_layers(spec_data, spec_resolved.parent)
    output = _resolve_output_path(output_path, spec_resolved, spec_data)
    layer_plan_output = _resolve_layer_plan_path(save_layer_plan, output)

    filter_complex = _build_filter_complex(canvas, layers)
    args = _build_ffmpeg_args(canvas, layers, filter_complex, output)
    receipt = _build_layer_plan(spec_bytes, canvas, layers, filter_complex, output)

    with _timed_operation() as timing:
        _run_ffmpeg(args)

    if layer_plan_output is not None:
        Path(layer_plan_output).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")

    return _build_composite_result(output, timing, receipt, layer_plan_output)


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
    _validate_color(canvas.background, "canvas.background")
    return canvas


def _parse_layers(spec_data: dict[str, Any], spec_dir: Path) -> list[_ResolvedLayer]:
    unsupported = sorted(_P1_UNSUPPORTED_TOP_LEVEL & set(spec_data))
    if unsupported:
        raise MCPVideoError(
            f"unsupported composite-layers P1 field(s): {unsupported}",
            error_type="validation_error",
            code="unsupported_compositor_feature",
        )
    raw_layers = spec_data.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise MCPVideoError("layers must be a non-empty list", error_type="validation_error", code="invalid_layers")
    seen: set[str] = set()
    resolved: list[_ResolvedLayer] = []
    for offset, raw in enumerate(raw_layers, start=1):
        if not isinstance(raw, dict):
            raise MCPVideoError("each layer must be an object", error_type="validation_error", code="invalid_layer")
        unsupported_layer_fields = sorted(_P1_UNSUPPORTED_LAYER_FIELDS & set(raw))
        if unsupported_layer_fields:
            raise MCPVideoError(
                f"layer {raw.get('id', offset)!r} uses deferred P2 field(s): {unsupported_layer_fields}",
                error_type="validation_error",
                code="unsupported_compositor_feature",
            )
        layer = _parse_layer(raw)
        if layer.id in seen:
            raise MCPVideoError(
                f"duplicate layer id: {layer.id}",
                error_type="validation_error",
                code="duplicate_layer_id",
            )
        seen.add(layer.id)
        src, receipt_src = _resolve_layer_source(layer, spec_dir)
        resolved.append(
            _ResolvedLayer(
                id=layer.id,
                type=layer.type,
                opacity=layer.opacity,
                position=layer.position,
                src=src,
                resolved_src=receipt_src,
                color=layer.color,
                blend=layer.blend,
                input_index=offset,
            )
        )
    return resolved


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
    if layer.blend != "normal":
        raise MCPVideoError(
            f"blend mode {layer.blend!r} is deferred beyond P1; use 'normal'",
            error_type="validation_error",
            code="unsupported_blend_mode",
        )
    _validate_opacity(layer.opacity, layer.id)
    _non_negative_number(layer.position["x"], f"{layer.id}.position.x")
    _non_negative_number(layer.position["y"], f"{layer.id}.position.y")
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
    if raw is None and isinstance(transform, dict):
        unsupported = {k for k in transform if k not in {"x", "y"}}
        if unsupported:
            raise MCPVideoError(
                f"transform field(s) {sorted(unsupported)} are deferred beyond P1",
                error_type="validation_error",
                code="unsupported_compositor_feature",
            )
        raw = transform
    if raw is None:
        raw = {"x": data.pop("x", 0), "y": data.pop("y", 0)}
    if not isinstance(raw, dict):
        raise MCPVideoError("position must be an object", error_type="validation_error", code="invalid_position")
    return {"x": float(raw.get("x", 0)), "y": float(raw.get("y", 0))}


def _resolve_layer_source(layer: _Layer, spec_dir: Path) -> tuple[str | None, str | None]:
    if layer.type == "solid":
        return None, None
    if layer.src is None:
        raise MCPVideoError(
            f"layer {layer.id!r} requires src",
            error_type="validation_error",
            code="missing_layer_src",
        )
    candidate = Path(layer.src)
    if candidate.is_absolute():
        validated = Path(_validate_input_path(str(candidate))).resolve()
    else:
        if ".." in candidate.parts:
            resolved_candidate = (spec_dir / candidate).resolve()
            if not _is_relative_to(resolved_candidate, spec_dir):
                raise MCPVideoError(
                    f"layer {layer.id!r} source escapes the spec directory",
                    error_type="validation_error",
                    code="unsafe_layer_source",
                )
        validated = Path(_validate_input_path(str(spec_dir / candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                f"layer {layer.id!r} source escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    receipt_src = _receipt_source(validated, spec_dir)
    return str(validated), receipt_src


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


def _build_ffmpeg_args(canvas: _Canvas, layers: list[_ResolvedLayer], filter_complex: str, output_path: str) -> list[str]:
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
    image_output = Path(output_path).suffix.lower() in _IMAGE_OUTPUT_SUFFIXES
    args.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-an"])
    if image_output:
        args.extend(["-frames:v", "1", "-update", "1"])
    else:
        args.extend(["-t", _num(canvas.duration), "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p"])
    args.append(output_path)
    return args


def _build_filter_complex(canvas: _Canvas, layers: list[_ResolvedLayer]) -> str:
    chains = ["[0:v]format=rgba[base0]"]
    previous = "base0"
    for idx, layer in enumerate(layers, start=1):
        layer_label = f"layer{idx}"
        out_label = "vout" if idx == len(layers) else f"base{idx}"
        opacity = _escape_ffmpeg_filter_value(f"{_validate_opacity(layer.opacity, layer.id):.2f}")
        x = _escape_ffmpeg_filter_value(_num(layer.position["x"]))
        y = _escape_ffmpeg_filter_value(_num(layer.position["y"]))
        chains.append(f"[{idx}:v]format=rgba,colorchannelmixer=aa={opacity}[{layer_label}]")
        overlay = f"[{previous}][{layer_label}]overlay={x}:{y}:format=auto:eof_action=pass"
        overlay = f"{overlay},format=yuv420p[{out_label}]" if idx == len(layers) else f"{overlay}[{out_label}]"
        chains.append(overlay)
        previous = out_label
    return ";".join(chains)


def _build_layer_plan(
    spec_bytes: bytes,
    canvas: _Canvas,
    layers: list[_ResolvedLayer],
    filter_complex: str,
    output_path: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": "video_composite_layers",
        "spec_hash": "sha256:" + hashlib.sha256(spec_bytes).hexdigest(),
        "canvas": canvas.model_dump(),
        "layers": [
            {
                "id": layer.id,
                "type": layer.type,
                "resolved_src": layer.resolved_src,
                "opacity": layer.opacity,
                "position": layer.position,
                "blend": layer.blend,
                "color": layer.color,
            }
            for layer in layers
        ],
        "filtergraph_summary": [
            "canvas normalized to rgba",
            "layers overlaid bottom-to-top with normal alpha compositing",
            "per-layer opacity applied via colorchannelmixer alpha",
        ],
        "filtergraph_hash": "sha256:" + hashlib.sha256(filter_complex.encode("utf-8")).hexdigest(),
        "output_path": output_path,
        "render_determinism_scope": (
            "layer-plan receipt only; rendered bytes are not promised portable across FFmpeg builds in P1"
        ),
    }


def _build_composite_result(
    output_path: str,
    timing: dict[str, float | None],
    receipt: dict[str, Any],
    layer_plan_path: str | None,
) -> CompositeLayerResult:
    if Path(output_path).suffix.lower() in _IMAGE_OUTPUT_SUFFIXES:
        return CompositeLayerResult(
            output_path=output_path,
            operation="composite_layers",
            format=Path(output_path).suffix.lower().lstrip("."),
            elapsed_ms=timing["elapsed_ms"],
            layer_plan_path=layer_plan_path,
            layer_plan=receipt,
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
    )


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
        raise MCPVideoError(f"{name} must be a positive integer", error_type="validation_error", code="invalid_parameter")


def _positive_number(value: float, name: str) -> None:
    number = _sanitize_ffmpeg_number(value, name)
    if number <= 0:
        raise MCPVideoError(f"{name} must be positive", error_type="validation_error", code="invalid_parameter")


def _non_negative_number(value: float, name: str) -> None:
    number = _sanitize_ffmpeg_number(value, name)
    if number < 0:
        raise MCPVideoError(f"{name} must be non-negative", error_type="validation_error", code="invalid_parameter")


def _num(value: float) -> str:
    number = _sanitize_ffmpeg_number(value, "ffmpeg number")
    if number.is_integer():
        return str(int(number))
    return f"{number:.6f}".rstrip("0").rstrip(".")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _receipt_source(path: Path, spec_dir: Path) -> str:
    with _suppress_value_error():
        return os.fspath(path.relative_to(spec_dir))
    return os.fspath(path)


class _suppress_value_error:
    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return exc_type is ValueError
