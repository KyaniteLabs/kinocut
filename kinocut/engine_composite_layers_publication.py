"""Separate media and JSON-plan staging for the layer compositor."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path

from .errors import MCPVideoError
from .ffmpeg_helpers import _atomic_artifact, _atomic_output, _open_staged_writer, _validate_artifact_path


def resolve_layer_plan_path(save_layer_plan: str | None, output_path: str) -> str | None:
    if save_layer_plan is None:
        return None
    path = save_layer_plan
    if not Path(path).is_absolute():
        path = str(Path(output_path).parent / path)
    alias = os.path.realpath(path) == os.path.realpath(output_path)
    if not alias and os.path.exists(path) and os.path.exists(output_path):
        alias = os.path.samefile(path, output_path)
    if alias:
        raise MCPVideoError("Layer plan path aliases the media output", code="invalid_output_path")
    if Path(path).suffix.lower() != ".json":
        raise MCPVideoError("Layer plan must be a JSON artifact", code="invalid_output_path")
    _validate_artifact_path(path)
    return path


def publish_composite(output, plan_path, args, receipt, dry_run, render, file_hash, build_result, timed_operation):
    """Finish both staged artifacts before publishing media, then its plan.

    Each replacement is atomic individually. This does not claim a filesystem
    transaction spanning two files if publication itself fails between them.
    """
    with contextlib.ExitStack() as stack:
        staged_plan = stack.enter_context(_atomic_artifact(plan_path)) if plan_path is not None else None
        if dry_run:
            timing = {"elapsed_ms": None}
            result = build_result(output, timing, receipt, plan_path, dry_run=True)
        else:
            staged_media = stack.enter_context(_atomic_output(output))
            with timed_operation() as timing:
                render([*args[:-1], staged_media])
            receipt["output_hash"] = file_hash(staged_media)
            result = build_result(staged_media, timing, receipt, plan_path, dry_run=False)
        if staged_plan is not None:
            with _open_staged_writer(staged_plan) as stream:
                stream.write((json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return result.model_copy(update={"output_path": output})
