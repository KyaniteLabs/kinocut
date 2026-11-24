"""Layer ``src``/``mask``/``matte`` path resolution for the composite engine.

Extracted from ``engine_composite_layers`` to keep that module under its size
budget. Every layer path — RELATIVE *and* ABSOLUTE — must resolve UNDER the
spec directory: a relative path that climbs out with ``..`` fails closed, and an
absolute ``src``/``mask``/``matte`` pointing outside the spec tree (e.g. at
``/etc/passwd`` or any other out-of-tree file) fails closed too. The absolute
branch previously honored any readable absolute path; confining it to
``spec_dir`` closes that read-any-file hole for the direct ``video_composite_layers``
tool and backstops the workflow path (whose synthesized spec sits at the
workspace root, so ``spec_dir`` == the workspace).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .errors import MCPVideoError
from .ffmpeg_helpers import _escape_ffmpeg_filter_value, _format_ffmpeg_number, _validate_input_path


def resolve_layer_source(layer: Any, spec_dir: Path) -> tuple[str | None, str | None]:
    if layer.type == "solid":
        return None, None
    if layer.src is None:
        raise MCPVideoError(
            "a layer requires src",
            error_type="validation_error",
            code="missing_layer_src",
        )
    candidate = Path(layer.src)
    if candidate.is_absolute():
        validated = Path(_validate_input_path(str(candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                "a layer source escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    else:
        if ".." in candidate.parts:
            resolved_candidate = (spec_dir / candidate).resolve()
            if not _is_relative_to(resolved_candidate, spec_dir):
                raise MCPVideoError(
                    "a layer source escapes the spec directory",
                    error_type="validation_error",
                    code="unsafe_layer_source",
                )
        validated = Path(_validate_input_path(str(spec_dir / candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                "a layer source escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    return str(validated), _receipt_source(validated, spec_dir)


def resolve_mask_source(layer: Any, spec_dir: Path) -> tuple[str | None, str | None]:
    mask = layer.mask or layer.matte
    if mask is None:
        return None, None
    candidate = Path(mask)
    if candidate.is_absolute():
        validated = Path(_validate_input_path(str(candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                "a layer mask escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    else:
        validated = Path(_validate_input_path(str(spec_dir / candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                "a layer mask escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    return str(validated), _receipt_source(validated, spec_dir)


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


def _start_shift(layer: Any, source_type: str) -> str:
    """Delay a video source so its first frame plays at the layer start.

    The enable window only hides the layer before ``start``; without this
    shift a video layer keeps playing from the canvas origin, so its opening
    frames are lost and a clip shorter than ``start`` never shows at all.
    """
    if source_type != "video" or not layer.start:
        return ""
    safe_start = _escape_ffmpeg_filter_value(_format_ffmpeg_number(layer.start))
    return f"setpts=PTS-STARTPTS+{safe_start}/TB,"


def _enable_expression(layer: Any) -> str:
    if layer.start is None:
        return ""
    safe_start = _escape_ffmpeg_filter_value(_format_ffmpeg_number(layer.start))
    if layer.duration is None:
        return f":enable='gte(t\\,{safe_start})'"
    safe_end = _escape_ffmpeg_filter_value(_format_ffmpeg_number(layer.start + layer.duration))
    return f":enable='between(t\\,{safe_start}\\,{safe_end})'"


def _probe_layer_source_size(layer: Any) -> tuple[int, int] | None:
    """Return intrinsic (w, h) of a real image/video layer when available."""
    if not getattr(layer, "src", None):
        return None
    if layer.type == "image":
        try:
            from PIL import Image

            with Image.open(layer.src) as img:
                return int(img.width), int(img.height)
        except Exception:
            return None
    if layer.type == "video":
        try:
            from .engine_probe import probe

            info = probe(layer.src)
            if info.width and info.height:
                return int(info.width), int(info.height)
        except Exception:
            return None
    return None


def _known_mask_target_size(layer: Any, canvas: Any, *, full_canvas_blend: bool) -> tuple[int, int] | None:
    """Return exact (w, h) for mask scaling when known, avoiding deprecated scale2ref."""
    if full_canvas_blend:
        return canvas.width, canvas.height
    if layer.rotation is not None or layer.scale is not None:
        return None
    if layer.width is not None and layer.height is not None:
        return int(layer.width), int(layer.height)
    if layer.width is not None or layer.height is not None:
        return None
    if layer.type == "solid":
        return canvas.width, canvas.height
    return _probe_layer_source_size(layer)


def _mask_merge_chains(
    layer: Any,
    canvas: Any,
    *,
    layer_label: str,
    chain: str,
    mask_type: str,
    mask_effects: list[str],
    full_canvas_blend: bool,
) -> list[str]:
    """Build layer + mask chains with aligned PTS before alphamerge."""
    mask_label = f"{layer_label}mask"
    processed_mask_label = f"{mask_label}processed"
    layer_pts = "setpts=PTS-STARTPTS," if layer.type == "video" else ""
    mask_pts = "setpts=PTS-STARTPTS," if mask_type == "video" else ""
    out = [
        f"[{layer.input_index}:v]{layer_pts}{chain}[{layer_label}raw]",
        f"[{layer.mask_input_index}:v]{mask_pts}format=gray[{mask_label}raw]",
        *mask_effects,
    ]
    post_shift = _start_shift(layer, "video" if "video" in (layer.type, mask_type) else layer.type).rstrip(",")
    merge_tail = f",{post_shift}" if post_shift else ""
    target = _known_mask_target_size(layer, canvas, full_canvas_blend=full_canvas_blend)
    if target is not None:
        w, h = target
        out.append(f"[{processed_mask_label}]scale={w}:{h}[{mask_label}]")
        out.append(f"[{layer_label}raw][{mask_label}]alphamerge{merge_tail}[{layer_label}]")
    else:
        layer_ref_label = f"{layer_label}ref"
        # Bare scale2ref (no rw/rh) stays portable across FFmpeg 6/7/8.
        out.append(f"[{processed_mask_label}][{layer_label}raw]scale2ref[{mask_label}][{layer_ref_label}]")
        out.append(f"[{layer_ref_label}][{mask_label}]alphamerge{merge_tail}[{layer_label}]")
    return out
