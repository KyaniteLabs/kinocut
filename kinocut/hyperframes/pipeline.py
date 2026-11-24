"""Render a composition and apply validated Kinocut post-processing steps."""

from __future__ import annotations

from collections.abc import Callable
from inspect import signature
from pathlib import Path
from typing import Any

from ..errors import HyperframesRenderError, MCPVideoError
from ..ffmpeg_helpers import _validate_output_path
from ..validation_errors import rejected_value
from .models import HyperframesPipelineResult
from .ops import render
from .validation import _validate_post_step_values


def _post_process_ops() -> dict[str, Callable]:
    """Return the post-processing operation registry for render_and_post."""
    from .. import engine as _video_engine

    return {
        "resize": _video_engine.resize,
        "convert": _video_engine.convert,
        "add_audio": _video_engine.add_audio,
        "normalize_audio": _video_engine.normalize_audio,
        "add_text": _video_engine.add_text,
        "fade": _video_engine.fade,
        "watermark": _video_engine.watermark,
    }


def _post_steps(post_process, op_map):
    if not isinstance(post_process, list):
        raise MCPVideoError(
            "Expected a list of post-processing steps", error_type="validation_error", code="invalid_parameter"
        )
    steps = []
    for op in post_process:
        if not isinstance(op, dict):
            raise MCPVideoError(
                "Expected a post-processing object", error_type="validation_error", code="invalid_parameter"
            )
        op_type = op.get("op", op.get("type", ""))
        if not isinstance(op_type, str) or op_type not in op_map:
            raise MCPVideoError(
                f"Unknown post-processing operation: {rejected_value(op_type)}. Valid operations: {', '.join(op_map)}",
                error_type="validation_error",
                code="invalid_parameter",
            )
        params = op.get("params", {})
        if not isinstance(params, dict) or "output_path" in params:
            raise MCPVideoError(
                "Invalid post-processing params", error_type="validation_error", code="invalid_parameter"
            )
        try:
            signature(op_map[op_type]).bind("input", output_path=None, **params)
        except TypeError:
            raise MCPVideoError(
                "Invalid post-processing arguments", error_type="validation_error", code="invalid_parameter"
            ) from None
        steps.append((op_type, params))
    return steps


def render_and_post(
    project_path: str,
    post_process: list[dict[str, Any]],
    output_path: str | None = None,
) -> HyperframesPipelineResult:
    """Render a Hyperframes composition, then apply Kinocut post-processing."""
    # Step 1: Render with Hyperframes. ``output_path`` names the *final* artifact:
    # when there are post-processing steps the last one writes it, so the
    # intermediate render goes to its default location instead of colliding with it.
    op_map = _post_process_ops()
    steps = _post_steps(post_process, op_map)
    for op_type, params in steps:
        _validate_post_step_values(op_type, params)
    if output_path is not None:
        validated_output = _validate_output_path(output_path)
        if Path(validated_output).is_dir():
            raise MCPVideoError(
                "Output path must be a file, not a directory",
                error_type="validation_error",
                code="invalid_output_path",
            )
    render_result = render(project_path, output_path=output_path if not steps else None)
    hyperframes_output = render_result.output_path
    if not render_result.success:
        raise HyperframesRenderError(
            "hyperframes render",
            0,
            "",
            reason="Render completed but the output artifact was not created",
        )

    # Step 2: Post-process with the Kinocut engine
    operations: list[str] = []
    current_input = hyperframes_output

    for i, (op_type, params) in enumerate(steps):
        is_last = i == len(steps) - 1
        step_output = output_path if is_last else None
        result = op_map[op_type](current_input, output_path=step_output, **params)
        current_input = result.output_path
        operations.append(op_type)

    return HyperframesPipelineResult(
        hyperframes_output=hyperframes_output,
        final_output=current_input,
        operations=operations,
    )
