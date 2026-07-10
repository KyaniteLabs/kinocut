"""Batch operation dispatcher for the FFmpeg engine."""

from __future__ import annotations

import logging
import os
from typing import Any

from .engine_audio_normalize import normalize_audio
from .engine_convert import convert
from .engine_edit import trim
from .engine_fade import fade
from .engine_filters import apply_filter
from .engine_resize import resize
from .engine_speed import speed
from .engine_watermark import watermark
from .errors import MCPVideoError
from .ffmpeg_helpers import _validate_input_path, _validate_output_path
from .models import EditResult

VALID_BATCH_OPERATIONS = {
    "trim",
    "resize",
    "convert",
    "filter",
    "blur",
    "color_grade",
    "watermark",
    "speed",
    "fade",
    "normalize_audio",
}


def _validate_batch_operation(operation: str) -> None:
    if operation not in VALID_BATCH_OPERATIONS:
        raise MCPVideoError(
            f"Unknown operation '{operation}'. Valid operations: {sorted(VALID_BATCH_OPERATIONS)}",
            error_type="validation_error",
            code="invalid_operation",
        )


def video_batch(
    inputs: list[str],
    operation: str,
    params: dict[str, Any] | None = None,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """Apply the same operation to multiple video files."""
    if not inputs:
        return {
            "success": False,
            "error": {"type": "input_error", "code": "empty_inputs", "message": "No input files provided"},
        }

    params = params or {}
    _validate_batch_operation(operation)
    if output_dir:
        try:
            output_dir = _validate_output_path(output_dir)
        except MCPVideoError as exc:
            if exc.code != "unsafe_path":
                raise
            return {
                "success": False,
                "total": len(inputs),
                "succeeded": 0,
                "failed": len(inputs),
                "results": [{"input": input_path, "success": False, "error": str(exc)} for input_path in inputs],
            }

    results = []
    succeeded = 0
    failed = 0

    for input_path in inputs:
        try:
            input_path = _validate_input_path(input_path)
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
            result = _run_batch_operation(input_path, operation, params, output_dir)
            results.append({"input": input_path, "success": True, "output_path": result.output_path})
            succeeded += 1
        except Exception as e:
            logging.warning("Batch operation failed for %s: %s", input_path, e)
            results.append({"input": input_path, "success": False, "error": str(e)})
            failed += 1

    return {
        "success": failed == 0,
        "total": len(inputs),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }


def _run_batch_operation(
    input_path: str,
    operation: str,
    params: dict[str, Any],
    output_dir: str | None,
) -> EditResult:
    def _batch_output(ext: str | None = None) -> str | None:
        if output_dir:
            name = os.path.splitext(os.path.basename(input_path))[0]
            ext = ext or ".mp4"
            return os.path.join(output_dir, f"{name}_{operation}{ext}")
        return None

    if operation == "trim":
        return trim(
            input_path,
            start=params.get("start", "0"),
            duration=params.get("duration"),
            end=params.get("end"),
            output_path=_batch_output(),
        )
    if operation == "resize":
        return resize(
            input_path,
            width=params.get("width"),
            height=params.get("height"),
            aspect_ratio=params.get("aspect_ratio"),
            quality=params.get("quality", "high"),
            output_path=_batch_output(),
        )
    if operation == "convert":
        out_ext = f".{params.get('format', 'mp4')}"
        return convert(
            input_path,
            format=params.get("format", "mp4"),
            quality=params.get("quality", "high"),
            output_path=_batch_output(out_ext),
        )
    if operation == "filter":
        return apply_filter(
            input_path,
            filter_type=params.get("filter_type", "blur"),
            params=params.get("filter_params", {}),
            output_path=_batch_output(),
        )
    if operation == "blur":
        return apply_filter(
            input_path, filter_type="blur", params=params.get("filter_params", {}), output_path=_batch_output()
        )
    if operation == "color_grade":
        return apply_filter(
            input_path,
            filter_type="color_preset",
            params={"preset": params.get("preset", "warm")},
            output_path=_batch_output(),
        )
    if operation == "watermark":
        return watermark(
            input_path,
            image_path=params.get("image_path", ""),
            position=params.get("position", "bottom-right"),
            opacity=params.get("opacity", 0.7),
            output_path=_batch_output(),
        )
    if operation == "speed":
        return speed(input_path, factor=params.get("factor", 1.0), output_path=_batch_output())
    if operation == "fade":
        return fade(
            input_path,
            fade_in=params.get("fade_in", 0.5),
            fade_out=params.get("fade_out", 0.5),
            output_path=_batch_output(),
        )
    if operation == "normalize_audio":
        return normalize_audio(input_path, target_lufs=params.get("target_lufs", -16.0), output_path=_batch_output())
    raise MCPVideoError(
        f"Unknown operation '{operation}'. Valid operations: {sorted(VALID_BATCH_OPERATIONS)}",
        error_type="validation_error",
        code="invalid_operation",
    )
