"""Dry-run planner for the agent workflow engine.

``plan_workflow`` validates a job-spec first (reusing the fail-closed
validator) and then produces a NO-RENDER plan artifact: the ordered operation
graph, per-source probe results + content hashes (where the file exists),
declared output intents, a variant-expansion summary, and warnings for
runtime concerns (e.g. a not-yet-existing source) that are not structural
errors. No media is rendered and no file is written except the optional plan
JSON requested via ``save_plan``.

Field names trace to the workflow receipt schema (plan section 5a): the plan is
a distinct ``receipt_kind`` (``workflow_plan``) so an inspecting agent can tell
a dry-run plan apart from a render receipt, while sharing the render receipt's
field vocabulary (``schema_version``, ``versions``, ``spec_hash``, ``workflow``,
``sources``, ``steps``, ``outputs``, ``render_determinism_scope``).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path
from ._errors import INVALID_WORKFLOW_SPEC, workflow_error
from ._versions import RENDER_DETERMINISM_SCOPE, versions
from .spec import validate_spec_path
from .validator import validate_workflow_spec

_SOURCE_PREFIX = "@sources."
_WORK_PREFIX = "@work/"


def plan_workflow(spec_path: str, save_plan: str | None = None, variant: str | None = None) -> dict[str, Any]:
    """Produce a no-render plan artifact for a validated workflow job-spec.

    Validates ``spec_path`` first (fail-closed via the structural validator);
    on success builds the plan artifact by probing/hashing declared sources
    where they exist. Optionally writes the artifact to ``save_plan``.

    When ``variant`` is given, the plan reflects that variant's EFFECTIVE
    (post-override) steps and output paths and records ``workflow.variant``; the
    ``spec_hash`` stays the base spec-file hash (variant selection is not part of
    it — see §5a). Raises ``MCPVideoError`` (fail-closed) on a structurally
    invalid spec or unknown/malformed variant.
    """
    verdict = validate_workflow_spec(spec_path, variant=variant)
    resolved = validate_spec_path(spec_path)
    workspace_root = Path(os.path.realpath(resolved.parent))
    spec_bytes = resolved.read_bytes()

    warnings: list[dict[str, Any]] = []
    hash_cache: dict[str, str | None] = {}

    sources = _plan_sources(verdict, workspace_root, warnings, hash_cache)
    steps = _plan_steps(verdict, workspace_root, hash_cache)
    outputs = _plan_outputs(verdict)

    plan = {
        "schema_version": verdict["schema_version"],
        "receipt_kind": "workflow_plan",
        "tool": "video_workflow_plan",
        "versions": versions(),
        "spec_hash": "sha256:" + hashlib.sha256(spec_bytes).hexdigest(),
        "workflow": {"name": verdict["name"], "variant": variant},
        "sources": sources,
        "steps": steps,
        "outputs": outputs,
        "variants": [{"id": variant_id} for variant_id in verdict["variants"]],
        "warnings": warnings,
        "render_determinism_scope": RENDER_DETERMINISM_SCOPE,
    }

    if save_plan is not None:
        _write_plan(plan, save_plan)

    return plan


def _plan_sources(
    verdict: dict[str, Any],
    workspace_root: Path,
    warnings: list[dict[str, Any]],
    hash_cache: dict[str, str | None],
) -> list[dict[str, Any]]:
    """Build the per-source plan entries: resolved path, hash, and probe."""
    source_paths: dict[str, str] = verdict["source_paths"]
    entries: list[dict[str, Any]] = []
    for source_id in verdict["sources"]:
        relative = source_paths[source_id]
        absolute = workspace_root / relative
        if not absolute.exists():
            warnings.append(
                {
                    "code": "source_missing",
                    "source": source_id,
                    "message": (
                        f"source {source_id!r} path {relative!r} does not exist yet; "
                        "probe and hash are unavailable at plan time"
                    ),
                }
            )
            entries.append({"id": source_id, "resolved": relative, "source_hash": None, "probe": None})
            continue
        source_hash = _hash_if_exists(absolute, hash_cache)
        probe = _probe_source(absolute)
        if probe is None:
            warnings.append(
                {
                    "code": "source_unprobeable",
                    "source": source_id,
                    "message": f"source {source_id!r} path {relative!r} exists but could not be probed as video",
                }
            )
        entries.append({"id": source_id, "resolved": relative, "source_hash": source_hash, "probe": probe})
    return entries


def _plan_steps(
    verdict: dict[str, Any], workspace_root: Path, hash_cache: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Build the ordered operation list with hashes where the input exists."""
    source_paths: dict[str, str] = verdict["source_paths"]
    steps: list[dict[str, Any]] = []
    for step in verdict["steps"]:
        input_hashes = {
            key: _hash_ref(ref, workspace_root, source_paths, hash_cache)
            for key, ref in _iter_step_refs(step["inputs"])
        }
        steps.append(
            {
                "id": step["id"],
                "op": step["op"],
                "status": "pending",
                "inputs": step["inputs"],
                "input_hashes": input_hashes,
                "output": step["output"],
                "output_hash": None,
            }
        )
    return steps


def _iter_step_refs(inputs: dict[str, Any]) -> list[tuple[str, Any]]:
    """Yield (namespaced_key, ref) for single and multi-input steps.

    A list-valued input (e.g. ``merge``'s ``srcs``) expands to indexed keys
    (``srcs[0]``, ``srcs[1]``, ...) so each element gets its own hash slot.
    """
    pairs: list[tuple[str, Any]] = []
    for key, value in inputs.items():
        if isinstance(value, list):
            for index, ref in enumerate(value):
                pairs.append((f"{key}[{index}]", ref))
        else:
            pairs.append((key, value))
    return pairs


def _hash_ref(
    ref: Any, workspace_root: Path, source_paths: dict[str, str], hash_cache: dict[str, str | None]
) -> str | None:
    """Hash the file a resolved input ref points at, or None when unavailable.

    ``@work/`` refs are intermediates not produced at plan time (None). Source
    and raw-relative refs are hashed when the underlying file exists.
    """
    if not isinstance(ref, str) or ref.startswith(_WORK_PREFIX):
        return None
    if ref.startswith(_SOURCE_PREFIX):
        relative = source_paths.get(ref[len(_SOURCE_PREFIX) :])
        if relative is None:
            return None
        return _hash_if_exists(workspace_root / relative, hash_cache)
    return _hash_if_exists(workspace_root / ref, hash_cache)


def _plan_outputs(verdict: dict[str, Any]) -> list[dict[str, Any]]:
    """Build declared output intents (no output_hash until rendered)."""
    output_paths: dict[str, str] = verdict["output_paths"]
    return [{"id": output_id, "path": output_paths[output_id], "output_hash": None} for output_id in verdict["outputs"]]


def _hash_if_exists(absolute: Path, hash_cache: dict[str, str | None]) -> str | None:
    """Return the sha256 of an existing file (cached), or None if absent."""
    key = str(absolute)
    if key in hash_cache:
        return hash_cache[key]
    digest: str | None = None
    if absolute.is_file():
        sha = hashlib.sha256()
        with open(absolute, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                sha.update(chunk)
        digest = "sha256:" + sha.hexdigest()
    hash_cache[key] = digest
    return digest


def _probe_source(absolute: Path) -> dict[str, Any] | None:
    """Probe a source with the existing engine; None if it is not a video."""
    from ..engine_probe import probe

    try:
        info = probe(str(absolute))
    except MCPVideoError:
        return None
    return {"duration": info.duration, "resolution": info.resolution, "codec": info.codec}


def _write_plan(plan: dict[str, Any], save_plan: str) -> None:
    """Write the plan artifact as pretty, stable JSON (matches receipt writer)."""
    if not isinstance(save_plan, str) or not save_plan:
        raise workflow_error("save_plan must be a non-empty file path", INVALID_WORKFLOW_SPEC)
    _validate_artifact_path(save_plan)  # traversal / symlink / system-dir / dotfile / overwrite-non-json guard
    Path(save_plan).write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
