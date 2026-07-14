"""Workspace-confined ``composite_layers`` workflow op (the 7th allowlisted op).

The backing engine ``composite_layers(spec_path, ...)`` consumes a NESTED JSON
layer-spec whose ``layers[].src`` / ``layers[].mask`` resolve *relative to that
spec's own directory*. Passing a user-authored nested ``spec_path`` straight
through would let those nested media sources bypass BOTH workspace confinement
and per-step ``input_hashes`` — the exact reason composite was cut from the 1.6.0
allowlist (plan §9).

This module closes that hole by making the workflow layer OWN the layer-spec:

  * a composite step declares its layers under ``inputs.layers`` and each layer's
    ``src`` / ``mask`` MUST be a workflow ``@ref`` (``@sources.<id>`` / ``@work/<name>``)
    — arbitrary nested / absolute / ``../`` paths fail closed (``unsafe_workflow_source``);
  * every layer ``@ref`` is resolved + confined + hashed through the SAME executor
    machinery as every other op's inputs (``iter_composite_refs`` for the per-layer
    ``input_hashes``; ``_resolve_confined_input`` for the confined absolute path);
  * ``render_composite_step`` re-validates the layers against the bytes it renders
    (closing a validate/render TOCTOU), builds each synth layer from an EXPLICIT field
    allowlist (never a blind ``dict`` copy), and synthesizes a nested spec whose layer
    sources are the resolved, workspace-confined absolute paths. The spec is written at
    the WORKSPACE ROOT (so the engine's spec-dir confinement == workspace confinement),
    R1-guarded, handed to the engine, and removed after the render.

The only tunable ``params`` key is ``canvas`` (written into the synthesized spec,
never passed to the engine signature); its VALUE correctness stays the engine's
job at render time, exactly like every other op.
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ._errors import (
    INVALID_WORKFLOW_PARAMS,
    INVALID_WORKFLOW_SPEC,
    UNKNOWN_WORKFLOW_REF,
    UNSAFE_WORKFLOW_SOURCE,
    workflow_error,
)

COMPOSITE_OP = "composite_layers"

_SOURCE_PREFIX = "@sources."
_WORK_PREFIX = "@work/"

_SUPPORTED_LAYER_TYPES = frozenset({"video", "image", "solid"})
# The path-bearing layer fields; each MUST be a workflow @ref (never a raw path).
_REF_LAYER_FIELDS: tuple[str, ...] = ("src", "mask")
# Strict field allowlist for a workflow composite layer. Tighter than the engine's
# own set: it omits the path aliases (`matte`, `transform`, `anchor`) so the ONLY
# path-bearing fields are `src` / `mask`, both forced to @refs. Unknown fields fail
# closed here (and the engine re-validates its own set at render time).
_ALLOWED_LAYER_FIELDS = frozenset(
    {
        "id",
        "type",
        "src",
        "mask",
        "opacity",
        "position",
        "x",
        "y",
        "width",
        "height",
        "scale",
        "rotation",
        "pivot",
        "start",
        "duration",
        "color",
        "blend",
    }
)


def validate_composite_inputs(step: Any, source_ids: set[str], work_produced: set[str]) -> dict[str, Any]:
    """Structurally validate a composite step's ``inputs.layers`` (fail closed).

    Enforces the ``@ref``-only rule for every layer source and returns the verdict
    ``inputs`` (the resolved layer list with ``id``/``type``/``src``/``mask``), which
    downstream hashing (plan + receipt) iterates via ``iter_composite_refs``.
    """
    inputs = step.inputs
    if not isinstance(inputs, dict) or set(inputs) != {"layers"}:
        raise workflow_error(
            f"step {step.id!r} ({COMPOSITE_OP}) requires an 'inputs' object with only the key 'layers'",
            INVALID_WORKFLOW_SPEC,
        )
    layers = inputs["layers"]
    if not isinstance(layers, list) or not layers:
        raise workflow_error(
            f"step {step.id!r} ({COMPOSITE_OP}) 'layers' must be a non-empty list of layer objects",
            INVALID_WORKFLOW_SPEC,
        )
    seen_ids: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for offset, layer in enumerate(layers, start=1):
        resolved.append(_validate_layer(step.id, offset, layer, seen_ids, source_ids, work_produced))
    return {"layers": resolved}


def _validate_layer(
    step_id: str,
    offset: int,
    layer: Any,
    seen_ids: set[str],
    source_ids: set[str],
    work_produced: set[str],
) -> dict[str, Any]:
    if not isinstance(layer, dict):
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer #{offset} must be an object", INVALID_WORKFLOW_SPEC
        )
    unknown = sorted(set(layer) - _ALLOWED_LAYER_FIELDS)
    if unknown:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer #{offset} has unsupported field(s) {unknown}; "
            f"allowed: {sorted(_ALLOWED_LAYER_FIELDS)}",
            INVALID_WORKFLOW_SPEC,
        )
    layer_id = layer.get("id")
    if not isinstance(layer_id, str) or not layer_id:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer #{offset} requires a non-empty string id",
            INVALID_WORKFLOW_SPEC,
        )
    if layer_id in seen_ids:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) has a duplicate layer id: {layer_id!r}", INVALID_WORKFLOW_SPEC
        )
    seen_ids.add(layer_id)
    layer_type = layer.get("type")
    if layer_type not in _SUPPORTED_LAYER_TYPES:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} type must be one of "
            f"{sorted(_SUPPORTED_LAYER_TYPES)}, got {layer_type!r}",
            INVALID_WORKFLOW_SPEC,
        )
    for field in _REF_LAYER_FIELDS:
        ref = layer.get(field)
        if ref is not None:
            _validate_layer_ref(step_id, layer_id, field, ref, source_ids, work_produced)
    src = layer.get("src")
    if layer_type in ("video", "image") and not src:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} of type {layer_type!r} requires a 'src' @ref",
            INVALID_WORKFLOW_SPEC,
        )
    if layer_type == "solid" and src is not None:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) solid layer {layer_id!r} must not declare a 'src'",
            INVALID_WORKFLOW_SPEC,
        )
    return {"id": layer_id, "type": layer_type, "src": src, "mask": layer.get("mask")}


def _validate_layer_ref(
    step_id: str, layer_id: str, field: str, ref: Any, source_ids: set[str], work_produced: set[str]
) -> None:
    """A composite layer source must be a declared workflow @ref, else fail closed.

    Raw / absolute / ``../`` / ``@outputs`` / unknown-namespace values are rejected so
    NO nested path can bypass workspace confinement or per-layer hashing.
    """
    if not isinstance(ref, str) or not ref:
        raise workflow_error(
            f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} {field} must be a non-empty @ref string",
            INVALID_WORKFLOW_SPEC,
        )
    if ref.startswith(_SOURCE_PREFIX):
        if ref[len(_SOURCE_PREFIX) :] not in source_ids:
            raise workflow_error(
                f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} {field} references undeclared source {ref!r}",
                UNKNOWN_WORKFLOW_REF,
            )
        return
    if ref.startswith(_WORK_PREFIX):
        if ref[len(_WORK_PREFIX) :] not in work_produced:
            raise workflow_error(
                f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} {field} references {ref!r} "
                "which is not produced by a strictly-earlier step",
                UNKNOWN_WORKFLOW_REF,
            )
        return
    raise workflow_error(
        f"step {step_id!r} ({COMPOSITE_OP}) layer {layer_id!r} {field} must be a workflow @ref "
        f"(@sources.<id> or @work/<name>), got {ref!r}; nested, absolute, and ../ paths are not allowed",
        UNSAFE_WORKFLOW_SOURCE,
    )


def iter_composite_refs(inputs: Any) -> list[tuple[str, str]]:
    """Yield ``(layers[i].<field>, ref)`` for every layer source in order.

    Drives the per-layer ``input_hashes`` for both the dry-run plan and the render
    receipt so composite provenance is complete (one sha256 slot per layer source).
    """
    pairs: list[tuple[str, str]] = []
    layers = inputs.get("layers") if isinstance(inputs, dict) else None
    if not isinstance(layers, list):
        return pairs
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        for field in _REF_LAYER_FIELDS:
            ref = layer.get(field)
            if isinstance(ref, str) and ref:
                pairs.append((f"layers[{index}].{field}", ref))
    return pairs


def render_composite_step(
    adapter: Any,
    step: Any,
    workspace_root: Path,
    source_paths: dict[str, str],
    work_paths: dict[str, Path],
    run_dir_abs: Path,
    output_abs: Path | None,
    resolve_confined_input: Callable[[str, Path, dict[str, str], dict[str, Path]], Path],
    source_ids: set[str],
    work_ids: set[str],
) -> None:
    """Synthesize a workspace-confined layer spec and render it via the engine.

    The executor re-reads the spec independently of the validator, so the layers are
    RE-VALIDATED here against the exact bytes being rendered (``validate_composite_inputs``,
    the same @ref-only + ``_ALLOWED_LAYER_FIELDS`` allowlist the validator ran). This
    closes a validate/render (TOCTOU) divergence: an engine-honored but workflow-unlisted
    path field (``matte``/``transform``/``anchor``) can never ride a re-read into the engine.

    Each synth layer is then built from an EXPLICIT field allowlist (never ``dict(layer)``),
    every ``@ref`` resolved to its confined absolute path with the injected
    ``resolve_confined_input``. The synthesized spec is written at the WORKSPACE ROOT so the
    engine's own spec-dir confinement (absolute layer paths outside the spec dir fail closed)
    coincides exactly with workspace confinement; it is guarded by ``_confine_artifact_path``
    and removed after the render.
    """
    if output_abs is None:  # defensive: validator requires an output for composite
        raise workflow_error(f"step {step.id!r} ({COMPOSITE_OP}) requires an output target", INVALID_WORKFLOW_SPEC)
    # Re-validate the layers against the executor's own read (not the validator's), so a
    # matte/unlisted path field injected between the two reads fails closed before it can
    # reach the engine (and before anything is resolved or hashed from it).
    validate_composite_inputs(step, source_ids, work_ids)
    canvas = step.params.get("canvas")
    if not isinstance(canvas, dict):
        raise workflow_error(
            f"step {step.id!r} ({COMPOSITE_OP}) requires a 'canvas' object in params", INVALID_WORKFLOW_PARAMS
        )
    synth_layers: list[dict[str, Any]] = []
    for raw in step.inputs["layers"]:
        # Explicit allowlist copy — never a blind dict(raw) — so no engine-honored path
        # field outside _ALLOWED_LAYER_FIELDS (matte/transform/anchor) can survive.
        synth_layer = {key: raw[key] for key in _ALLOWED_LAYER_FIELDS if key in raw}
        for field in _REF_LAYER_FIELDS:
            ref = raw.get(field)
            if ref is None:
                continue
            confined = resolve_confined_input(ref, workspace_root, source_paths, work_paths)
            synth_layer[field] = str(confined)
        synth_layers.append(synth_layer)
    synth_spec = {"canvas": canvas, "layers": synth_layers}
    safe_id = step.id.replace("/", "_").replace("\\", "_")
    synth_path = workspace_root / f"mcp_video_composite_{run_dir_abs.name}_{safe_id}.json"
    _confine_synth_path(str(synth_path), workspace_root)
    synth_path.write_text(json.dumps(synth_spec), encoding="utf-8")
    try:
        adapter.engine_fn(spec_path=str(synth_path), output_path=str(output_abs))
    finally:
        with contextlib.suppress(OSError):
            synth_path.unlink()


def _confine_synth_path(path: str, workspace_root: Path) -> None:
    """Fail closed unless the synth-spec write resolves inside the workspace (R1 guard).

    Lazy-imported to avoid a planner<->composite import cycle; routes the synth write
    through the SAME realpath + workspace confinement every other workflow artifact uses,
    so a planted symlink at the synth path cannot redirect the write out of the workspace.
    """
    from .planner import _confine_artifact_path

    _confine_artifact_path(path, workspace_root, "composite synth spec")
