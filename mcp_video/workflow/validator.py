"""Fail-closed structural validator for the agent workflow engine.

Validates ONLY structural concerns and never renders media:
  * op membership in the allowlist,
  * ``@ref`` resolution across the @sources.* / @work/* / @outputs.* namespaces,
  * backward-reference-only ordering (a step may reference @work outputs from
    strictly-earlier steps only; forward/unknown refs fail closed),
  * per-op params (unknown keys rejected via engine-signature introspection),
  * workspace-confined path safety (absolute paths and ../ / symlink escapes
    fail closed).

Semantic/param *value* correctness stays the backing engine's job at render
time; here every violation raises an ``MCPVideoError`` with a specific ``code``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ..limits import MAX_WORKFLOW_STEPS, MAX_WORKFLOW_VARIANTS
from ._errors import (
    INVALID_WORKFLOW_PARAMS,
    INVALID_WORKFLOW_SPEC,
    UNKNOWN_WORKFLOW_REF,
    UNSAFE_WORKFLOW_SOURCE,
    UNSUPPORTED_WORKFLOW_OP,
    workflow_error,
)
from .ops import OP_ADAPTERS, OpAdapter
from .spec import WorkflowSpec, load_spec, parse_spec, validate_spec_path
from .variants import apply_variant_overrides

_SOURCE_PREFIX = "@sources."
_WORK_PREFIX = "@work/"
_OUTPUT_PREFIX = "@outputs."


def validate_workflow_spec(spec_path: str, variant: str | None = None) -> dict[str, Any]:
    """Validate a workflow job-spec, returning a structured verdict.

    When ``variant`` is given, the selected variant's overrides are merged into
    the spec first and the EFFECTIVE (post-override) spec is validated (an unknown
    variant id or a malformed override fails closed ``invalid_workflow_variant``).
    When ``variant`` is ``None``, the base spec is validated AND every declared
    variant is test-merged and structurally validated, so ``workflow-validate``
    proves each variant is renderable (malformed overrides / bad post-merge params
    fail closed here, not at render time).

    Raises ``MCPVideoError`` (fail-closed) on any structural violation.
    """
    resolved = validate_spec_path(spec_path)
    data = load_spec(resolved)
    workspace_root = Path(os.path.realpath(resolved.parent))
    if variant is not None:
        data = apply_variant_overrides(data, variant)
    spec = parse_spec(data)

    verdict_steps, source_paths, output_paths = _validate_structure(spec, workspace_root)
    _validate_variants(spec)
    if variant is None:
        _validate_declared_variants(data, spec, workspace_root)

    return {
        "valid": True,
        "schema_version": spec.schema_version,
        "name": spec.name,
        "variant": variant,
        "sources": sorted(spec.sources),
        "source_paths": source_paths,
        "outputs": sorted(spec.outputs),
        "output_paths": output_paths,
        "steps": verdict_steps,
        "ops": sorted({step.op for step in spec.steps}),
        "variants": [variant.id for variant in spec.variants],
    }


def _validate_structure(
    spec: WorkflowSpec, workspace_root: Path
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    """Run the shared structural checks (schema, steps, path safety) for one spec.

    Returns ``(verdict_steps, source_paths, output_paths)``. Variant declarations
    are validated separately so this can be reused to validate a merged variant
    spec without recursing into its (identical) variant list.
    """
    _check_schema_version(spec)
    _require_steps(spec)
    source_paths = _resolve_declared_paths(spec.sources, workspace_root, "sources")
    output_paths = _resolve_declared_paths(spec.outputs, workspace_root, "outputs")
    verdict_steps = _validate_steps(spec, workspace_root, set(spec.sources), set(spec.outputs))
    return verdict_steps, source_paths, output_paths


def _validate_declared_variants(data: dict[str, Any], spec: WorkflowSpec, workspace_root: Path) -> None:
    """Test-merge + structurally validate every declared variant (fail closed)."""
    for variant in spec.variants:
        merged = apply_variant_overrides(data, variant.id)
        _validate_structure(parse_spec(merged), workspace_root)


def _check_schema_version(spec: WorkflowSpec) -> None:
    if spec.schema_version != 1:
        raise workflow_error(
            f"unsupported workflow schema_version: {spec.schema_version} (expected 1)", INVALID_WORKFLOW_SPEC
        )


def _require_steps(spec: WorkflowSpec) -> None:
    if not spec.steps:
        raise workflow_error("workflow spec must declare at least one step", INVALID_WORKFLOW_SPEC)
    if len(spec.steps) > MAX_WORKFLOW_STEPS:
        raise workflow_error(
            f"workflow spec declares {len(spec.steps)} steps; the maximum is {MAX_WORKFLOW_STEPS}",
            INVALID_WORKFLOW_SPEC,
        )


def _resolve_declared_paths(declared: dict[str, Any], workspace_root: Path, label: str) -> dict[str, str]:
    """Resolve declared source/output paths, enforcing workspace confinement."""
    return {
        key: _resolve_workspace_path(entry.path, workspace_root, f"{label}.{key}.path")
        for key, entry in declared.items()
    }


def _resolve_workspace_path(raw: str, workspace_root: Path, label: str) -> str:
    """Return a workspace-relative posix path, or fail closed on any escape."""
    if not isinstance(raw, str) or not raw:
        raise workflow_error(f"{label} must be a non-empty string", INVALID_WORKFLOW_SPEC)
    if "\x00" in raw:
        raise workflow_error(f"{label} contains null bytes", UNSAFE_WORKFLOW_SOURCE)
    candidate = Path(raw)
    if candidate.is_absolute():
        raise workflow_error(
            f"{label} must be a relative path inside the workspace, got absolute path {raw!r}",
            UNSAFE_WORKFLOW_SOURCE,
        )
    resolved = Path(os.path.realpath(workspace_root / candidate))
    try:
        relative = resolved.relative_to(workspace_root)
    except ValueError:
        raise workflow_error(f"{label} escapes the workspace root: {raw!r}", UNSAFE_WORKFLOW_SOURCE) from None
    return relative.as_posix()


def _validate_steps(
    spec: WorkflowSpec, workspace_root: Path, source_ids: set[str], output_ids: set[str]
) -> list[dict[str, Any]]:
    seen_ids: set[str] = set()
    work_produced: set[str] = set()
    verdict: list[dict[str, Any]] = []
    for step in spec.steps:
        _validate_step_id(step.id, seen_ids)
        adapter = _resolve_op(step.op, step.id)
        resolved_inputs = _validate_inputs(step, adapter, workspace_root, source_ids, work_produced)
        _validate_params(step, adapter)
        _validate_output(step, adapter, output_ids, work_produced)
        verdict.append(
            {
                "id": step.id,
                "op": step.op,
                "inputs": resolved_inputs,
                "params": sorted(step.params),
                "output": step.output,
            }
        )
        if step.output and step.output.startswith(_WORK_PREFIX):
            work_produced.add(step.output[len(_WORK_PREFIX) :])
    return verdict


def _validate_step_id(step_id: str, seen: set[str]) -> None:
    if not step_id:
        raise workflow_error("each step requires a non-empty string id", INVALID_WORKFLOW_SPEC)
    if step_id in seen:
        raise workflow_error(f"duplicate step id: {step_id!r}", INVALID_WORKFLOW_SPEC)
    seen.add(step_id)


def _resolve_op(op: str, step_id: str) -> OpAdapter:
    adapter = OP_ADAPTERS.get(op)
    if adapter is None:
        raise workflow_error(f"step {step_id!r} uses unsupported workflow op: {op!r}", UNSUPPORTED_WORKFLOW_OP)
    return adapter


def _validate_inputs(
    step: Any, adapter: OpAdapter, workspace_root: Path, source_ids: set[str], work_produced: set[str]
) -> dict[str, Any]:
    inputs = step.inputs
    if not isinstance(inputs, dict) or not inputs:
        raise workflow_error(
            f"step {step.id!r} requires an 'inputs' object with key {adapter.input_key!r}", INVALID_WORKFLOW_SPEC
        )
    extra = sorted(set(inputs) - {adapter.input_key})
    if extra:
        raise workflow_error(
            f"step {step.id!r} ({step.op}) has unexpected input key(s) {extra}; expected only {adapter.input_key!r}",
            INVALID_WORKFLOW_SPEC,
        )
    if adapter.input_key not in inputs:
        raise workflow_error(
            f"step {step.id!r} ({step.op}) requires input key {adapter.input_key!r}", INVALID_WORKFLOW_SPEC
        )
    value = inputs[adapter.input_key]
    if adapter.multi_input:
        if not isinstance(value, list) or not value:
            raise workflow_error(
                f"step {step.id!r} ({step.op}) input {adapter.input_key!r} must be a non-empty list of refs",
                INVALID_WORKFLOW_SPEC,
            )
        resolved: Any = [_resolve_ref(step.id, ref, workspace_root, source_ids, work_produced) for ref in value]
    else:
        if isinstance(value, list):
            raise workflow_error(
                f"step {step.id!r} ({step.op}) input {adapter.input_key!r} must be a single ref, not a list",
                INVALID_WORKFLOW_SPEC,
            )
        resolved = _resolve_ref(step.id, value, workspace_root, source_ids, work_produced)
    return {adapter.input_key: resolved}


def _resolve_ref(
    step_id: str, ref: Any, workspace_root: Path, source_ids: set[str], work_produced: set[str]
) -> str:
    if not isinstance(ref, str) or not ref:
        raise workflow_error(f"step {step_id!r} has a non-string or empty input reference", INVALID_WORKFLOW_SPEC)
    if ref.startswith(_SOURCE_PREFIX):
        source_id = ref[len(_SOURCE_PREFIX) :]
        if source_id not in source_ids:
            raise workflow_error(f"step {step_id!r} references undeclared source {ref!r}", UNKNOWN_WORKFLOW_REF)
        return ref
    if ref.startswith(_WORK_PREFIX):
        name = ref[len(_WORK_PREFIX) :]
        if name not in work_produced:
            raise workflow_error(
                f"step {step_id!r} references {ref!r} which is not produced by a strictly-earlier step",
                UNKNOWN_WORKFLOW_REF,
            )
        return ref
    if ref.startswith(_OUTPUT_PREFIX):
        raise workflow_error(
            f"step {step_id!r} references {ref!r}; @outputs.<id> is an output target, not a step input",
            UNKNOWN_WORKFLOW_REF,
        )
    if ref.startswith("@"):
        raise workflow_error(f"step {step_id!r} uses unknown ref namespace {ref!r}", UNKNOWN_WORKFLOW_REF)
    # Raw path: allowed only if it stays inside the workspace root.
    _resolve_workspace_path(ref, workspace_root, f"step {step_id} input {ref!r}")
    return ref


def _validate_params(step: Any, adapter: OpAdapter) -> None:
    if not isinstance(step.params, dict):
        raise workflow_error(f"step {step.id!r} params must be an object", INVALID_WORKFLOW_SPEC)
    accepted = adapter.accepted_params()
    unknown = sorted(set(step.params) - accepted)
    if unknown:
        raise workflow_error(
            f"step {step.id!r} ({step.op}) has params the engine does not accept: {unknown}; "
            f"accepted: {sorted(accepted)}",
            INVALID_WORKFLOW_PARAMS,
        )
    adapter.validate_param_values(step.params, step.id)


def _validate_output(step: Any, adapter: OpAdapter, output_ids: set[str], work_produced: set[str]) -> None:
    if not adapter.has_output:
        if step.output is not None:
            raise workflow_error(
                f"step {step.id!r} op {step.op!r} is an inspection op and produces no output; remove 'output'",
                INVALID_WORKFLOW_SPEC,
            )
        return
    if step.output is None:
        raise workflow_error(
            f"step {step.id!r} op {step.op!r} requires an 'output' target (@work/<name> or @outputs.<id>)",
            INVALID_WORKFLOW_SPEC,
        )
    if not isinstance(step.output, str):
        raise workflow_error(f"step {step.id!r} output must be a string", INVALID_WORKFLOW_SPEC)
    if step.output.startswith(_WORK_PREFIX):
        name = step.output[len(_WORK_PREFIX) :]
        if not name:
            raise workflow_error(f"step {step.id!r} has an empty @work/ output name", INVALID_WORKFLOW_SPEC)
        if name in work_produced:
            raise workflow_error(f"step {step.id!r} reuses the @work output name {name!r}", INVALID_WORKFLOW_SPEC)
    elif step.output.startswith(_OUTPUT_PREFIX):
        output_id = step.output[len(_OUTPUT_PREFIX) :]
        if output_id not in output_ids:
            raise workflow_error(
                f"step {step.id!r} writes to undeclared output {step.output!r}", UNKNOWN_WORKFLOW_REF
            )
    else:
        raise workflow_error(
            f"step {step.id!r} output must be @work/<name> or @outputs.<id>, got {step.output!r}",
            INVALID_WORKFLOW_SPEC,
        )


def _validate_variants(spec: WorkflowSpec) -> None:
    if len(spec.variants) > MAX_WORKFLOW_VARIANTS:
        raise workflow_error(
            f"workflow spec declares {len(spec.variants)} variants; the maximum is {MAX_WORKFLOW_VARIANTS}",
            INVALID_WORKFLOW_SPEC,
        )
    seen: set[str] = set()
    for variant in spec.variants:
        if not variant.id:
            raise workflow_error("each variant requires a non-empty id", INVALID_WORKFLOW_SPEC)
        if variant.id in seen:
            raise workflow_error(f"duplicate variant id: {variant.id!r}", INVALID_WORKFLOW_SPEC)
        seen.add(variant.id)
        if not isinstance(variant.overrides, dict):
            raise workflow_error(f"variant {variant.id!r} overrides must be an object", INVALID_WORKFLOW_SPEC)
