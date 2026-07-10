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
from .ffmpeg_helpers import _validate_input_path


def resolve_layer_source(layer: Any, spec_dir: Path) -> tuple[str | None, str | None]:
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
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                f"layer {layer.id!r} source escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
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
                f"layer {layer.id!r} mask escapes the spec directory",
                error_type="validation_error",
                code="unsafe_layer_source",
            )
    else:
        validated = Path(_validate_input_path(str(spec_dir / candidate))).resolve()
        if not _is_relative_to(validated, spec_dir):
            raise MCPVideoError(
                f"layer {layer.id!r} mask escapes the spec directory",
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
