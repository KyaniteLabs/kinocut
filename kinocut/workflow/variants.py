"""Batch-variant override merge for the agent workflow engine.

A ``variants[]`` entry names an ``id`` plus a set of ``overrides`` that patch the
single ``sources``/``steps``/``outputs`` declaration so one spec emits N DISTINCT
outputs WITHOUT duplicating source declarations (plan §4). ``apply_variant_overrides``
returns a NEW spec dict with the selected variant's overrides applied and its
declared output paths auto-named with the variant id (so N variants -> N distinct
outputs), failing closed on an unknown variant id or a malformed override.

Override grammar (dotted keys; anything else fails closed
``invalid_workflow_variant``):
  * ``steps.<step_id>.params``        -> value dict, shallow-merged into the step params
  * ``steps.<step_id>.params.<name>`` -> value set as a single param
  * ``steps.<step_id>.output``        -> value str, replaces the step output target
  * ``outputs.<output_id>.path``      -> value str, replaces the declared output path

Unknown param NAMES are intentionally NOT rejected here: post-merge validation
re-runs engine-signature introspection and rejects them (``invalid_workflow_params``),
so the "introspection still enforced post-merge" guarantee holds. Source
declarations are never a valid override target — variants reuse them verbatim.
"""

from __future__ import annotations

import copy
from pathlib import PurePosixPath
from typing import Any

from ._errors import INVALID_WORKFLOW_VARIANT, workflow_error

_STEPS = "steps"
_OUTPUTS = "outputs"
_PARAMS = "params"
_OUTPUT = "output"
_PATH = "path"


def variant_ids(spec_data: dict[str, Any]) -> list[str]:
    """Return the ordered list of declared variant ids (empty if none/malformed)."""
    ids: list[str] = []
    for entry in spec_data.get("variants") or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]:
            ids.append(entry["id"])
    return ids


def apply_variant_overrides(spec_data: dict[str, Any], variant_id: str) -> dict[str, Any]:
    """Return a new spec dict with ``variant_id``'s overrides + output naming applied.

    Deep-copies ``spec_data`` (the base is never mutated), applies the variant's
    overrides, then suffixes each declared output path with ``.<variant_id>`` unless
    that output's path was itself overridden. Fails closed (``invalid_workflow_variant``)
    on an unknown variant id or a structurally malformed override.
    """
    variant = _find_variant(spec_data, variant_id)
    overrides = variant.get("overrides") or {}
    if not isinstance(overrides, dict):
        raise workflow_error(f"variant {variant_id!r} overrides must be an object", INVALID_WORKFLOW_VARIANT)
    merged = copy.deepcopy(spec_data)
    overridden_outputs: set[str] = set()
    for key, value in overrides.items():
        _apply_override(merged, variant_id, key, value, overridden_outputs)
    _name_variant_outputs(merged, variant_id, overridden_outputs)
    return merged


def _find_variant(spec_data: dict[str, Any], variant_id: str) -> dict[str, Any]:
    for entry in spec_data.get("variants") or []:
        if isinstance(entry, dict) and entry.get("id") == variant_id:
            return entry
    raise workflow_error(
        f"unknown variant id {variant_id!r}; declared variants: {variant_ids(spec_data) or '(none)'}",
        INVALID_WORKFLOW_VARIANT,
    )


def _apply_override(
    merged: dict[str, Any], variant_id: str, key: Any, value: Any, overridden_outputs: set[str]
) -> None:
    if not isinstance(key, str) or not key:
        raise workflow_error(f"variant {variant_id!r} has a non-string/empty override key", INVALID_WORKFLOW_VARIANT)
    parts = key.split(".")
    if parts[0] == _STEPS:
        _apply_step_override(merged, variant_id, key, parts, value)
    elif parts[0] == _OUTPUTS:
        _apply_output_override(merged, variant_id, key, parts, value, overridden_outputs)
    else:
        raise workflow_error(
            f"variant {variant_id!r} override key {key!r} must target "
            "steps.<id>.params[.<name>], steps.<id>.output, or outputs.<id>.path",
            INVALID_WORKFLOW_VARIANT,
        )


def _apply_step_override(merged: dict[str, Any], variant_id: str, key: str, parts: list[str], value: Any) -> None:
    if len(parts) < 3:
        raise workflow_error(
            f"variant {variant_id!r} override key {key!r} must be steps.<id>.params[.<name>] or steps.<id>.output",
            INVALID_WORKFLOW_VARIANT,
        )
    step = _find_step(merged, variant_id, parts[1], key)
    field = parts[2]
    if field == _PARAMS and len(parts) == 3:
        if not isinstance(value, dict):
            raise workflow_error(
                f"variant {variant_id!r} override {key!r} must be an object of params to merge",
                INVALID_WORKFLOW_VARIANT,
            )
        _step_params(step).update(value)
    elif field == _PARAMS and len(parts) == 4:
        _step_params(step)[parts[3]] = value
    elif field == _OUTPUT and len(parts) == 3:
        if not isinstance(value, str) or not value:
            raise workflow_error(
                f"variant {variant_id!r} override {key!r} output must be a non-empty string",
                INVALID_WORKFLOW_VARIANT,
            )
        step[_OUTPUT] = value
    else:
        raise workflow_error(
            f"variant {variant_id!r} override key {key!r} is not a supported step target",
            INVALID_WORKFLOW_VARIANT,
        )


def _step_params(step: dict[str, Any]) -> dict[str, Any]:
    params = step.get(_PARAMS)
    if not isinstance(params, dict):
        params = {}
        step[_PARAMS] = params
    return params


def _find_step(merged: dict[str, Any], variant_id: str, step_id: str, key: str) -> dict[str, Any]:
    for step in merged.get(_STEPS) or []:
        if isinstance(step, dict) and step.get("id") == step_id:
            return step
    raise workflow_error(
        f"variant {variant_id!r} override {key!r} targets unknown step {step_id!r}",
        INVALID_WORKFLOW_VARIANT,
    )


def _apply_output_override(
    merged: dict[str, Any], variant_id: str, key: str, parts: list[str], value: Any, overridden_outputs: set[str]
) -> None:
    if len(parts) != 3 or parts[2] != _PATH:
        raise workflow_error(
            f"variant {variant_id!r} override key {key!r} must be outputs.<id>.path",
            INVALID_WORKFLOW_VARIANT,
        )
    output_id = parts[1]
    outputs = merged.get(_OUTPUTS)
    if not isinstance(outputs, dict) or output_id not in outputs or not isinstance(outputs[output_id], dict):
        raise workflow_error(
            f"variant {variant_id!r} override {key!r} targets unknown output {output_id!r}",
            INVALID_WORKFLOW_VARIANT,
        )
    if not isinstance(value, str) or not value:
        raise workflow_error(
            f"variant {variant_id!r} override {key!r} path must be a non-empty string",
            INVALID_WORKFLOW_VARIANT,
        )
    outputs[output_id][_PATH] = value
    overridden_outputs.add(output_id)


def _name_variant_outputs(merged: dict[str, Any], variant_id: str, overridden_outputs: set[str]) -> None:
    """Suffix each declared output path with ``.<variant_id>`` (skip explicit overrides)."""
    outputs = merged.get(_OUTPUTS)
    if not isinstance(outputs, dict):
        return
    for output_id, entry in outputs.items():
        if output_id in overridden_outputs or not isinstance(entry, dict):
            continue
        path = entry.get(_PATH)
        if isinstance(path, str) and path:
            entry[_PATH] = _suffix_path(path, variant_id)


def _suffix_path(path: str, variant_id: str) -> str:
    """``output/final.mp4`` + ``square`` -> ``output/final.square.mp4`` (distinct per variant)."""
    posix = PurePosixPath(path)
    return str(posix.with_name(f"{posix.stem}.{variant_id}{posix.suffix}"))
