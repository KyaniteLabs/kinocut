"""Workspace-confined path resolution for the workflow executor.

Every input the workflow spec names is a symbolic ref (``@sources.<name>``,
``@work/<name>``) or a raw relative path. This module turns those refs
into absolute paths on disk and refuses the ones that escape the
workspace root.

The confinement check is repeated at execution time, not only at
validation time: a symlink swapped in between the two would otherwise
escape.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from ..validation_errors import rejected_value
from ._errors import INVALID_WORKFLOW_SPEC, UNSAFE_WORKFLOW_SOURCE, workflow_error
from .composite import iter_composite_refs
from .ops import CompositeOpAdapter, OpAdapter
from .planner import _hash_if_exists, _iter_step_refs

SOURCE_PREFIX = "@sources."
WORK_PREFIX = "@work/"
OUTPUT_PREFIX = "@outputs."
WORK_STEM_PREFIX = "mcp_video_"


def resolve_confined_input(
    ref: str, workspace_root: Path, source_paths: dict[str, str], work_paths: dict[str, Path]
) -> Path:
    """Resolve a workflow @ref to a workspace-confined absolute path (composite layer source).

    Reuses the SAME resolution + realpath-confinement the executor applies to every input,
    so a composite layer source is confined identically to any other op's source (a symlink
    swapped in after validation still fails closed at execution time).
    """
    return _confine_to_workspace(_resolve_ref_path(ref, workspace_root, source_paths, work_paths), workspace_root, ref)


def resolve_engine_input(
    adapter: OpAdapter,
    inputs: dict[str, Any],
    workspace_root: Path,
    source_paths: dict[str, str],
    work_paths: dict[str, Path],
) -> Any:
    """Resolve the spec ``inputs`` into concrete engine-ready path(s)."""
    value = inputs[adapter.input_key]
    if adapter.multi_input:
        return [str(_resolve_ref_path(ref, workspace_root, source_paths, work_paths)) for ref in value]
    return str(_resolve_ref_path(value, workspace_root, source_paths, work_paths))


def _resolve_ref_path(
    ref: str, workspace_root: Path, source_paths: dict[str, str], work_paths: dict[str, Path]
) -> Path:
    """Map a symbolic (or raw-relative) input ref to its absolute path on disk."""
    if ref.startswith(SOURCE_PREFIX):
        return workspace_root / source_paths[ref[len(SOURCE_PREFIX) :]]
    if ref.startswith(WORK_PREFIX):
        name = ref[len(WORK_PREFIX) :]
        path = work_paths.get(name)
        if path is None:  # defensive: validator guarantees backward production
            raise workflow_error(
                f"internal: @work ref {rejected_value(ref)!r} was not produced by an earlier step",
                INVALID_WORKFLOW_SPEC,
            )
        return path
    # Raw relative ref: re-confine at execution time (a symlink swapped in AFTER
    # validation could otherwise escape — validate->execute TOCTOU).
    return _confine_to_workspace(workspace_root / ref, workspace_root, ref)


def _confine_to_workspace(candidate: Path, workspace_root: Path, ref: str) -> Path:
    """Fail closed if ``candidate`` resolves outside ``workspace_root`` (realpath check)."""
    real = Path(os.path.realpath(candidate))
    try:
        real.relative_to(workspace_root)
    except ValueError:
        raise workflow_error(
            f"input ref {rejected_value(ref)!r} escapes the workspace root at execution time", UNSAFE_WORKFLOW_SOURCE
        ) from None
    return candidate


def hash_inputs(
    inputs: dict[str, Any],
    workspace_root: Path,
    source_paths: dict[str, str],
    work_paths: dict[str, Path],
    hash_cache: dict[str, str | None],
    adapter: OpAdapter | None = None,
) -> dict[str, str | None]:
    """Real sha256 for every consumed input (``src`` / ``srcs[i]`` / composite layer slots)."""
    # composite records one hash per layer source (layers[i].src/mask); every other op
    # hashes its flat src/srcs refs. Both drive complete per-step provenance.
    ref_pairs = iter_composite_refs(inputs) if isinstance(adapter, CompositeOpAdapter) else _iter_step_refs(inputs)
    hashes: dict[str, str | None] = {}
    for key, ref in ref_pairs:
        path = _resolve_ref_path(ref, workspace_root, source_paths, work_paths)
        hashes[key] = _hash_if_exists(path, hash_cache)
    return hashes


# --- @work directory + output resolution -------------------------------------


def make_run_dir(workspace_root: Path, spec_hash: str) -> tuple[str, Path]:
    """Create a unique per-run @work directory (spec-hash prefix + run id)."""
    prefix = spec_hash.split(":", 1)[-1][:8]
    run_id = uuid.uuid4().hex[:8]
    rel = f"work/{prefix}-{run_id}"
    absolute = workspace_root / rel
    absolute.mkdir(parents=True, exist_ok=True)
    return rel, absolute


def resolve_output(
    output: str | None,
    workspace_root: Path,
    run_dir_rel: str,
    run_dir_abs: Path,
    output_paths: dict[str, str],
    work_paths: dict[str, Path],
) -> tuple[str | None, Path | None]:
    """Resolve a step's output target to (workspace-relative, absolute) paths.

    ``@work/<name>`` targets land inside this run's dir with an ``mcp_video_``
    stem prefix; ``@outputs.<id>`` targets resolve to the declared output path.
    Registers the @work mapping so later steps can consume it.
    """
    if output is None:
        return None, None
    if output.startswith(WORK_PREFIX):
        name = output[len(WORK_PREFIX) :]
        filename = WORK_STEM_PREFIX + name.replace("/", "_").replace("\\", "_")
        absolute = run_dir_abs / filename
        ensure_parent(absolute)
        work_paths[name] = absolute
        return f"{run_dir_rel}/{filename}", absolute
    if output.startswith(OUTPUT_PREFIX):
        rel = output_paths[output[len(OUTPUT_PREFIX) :]]
        absolute = workspace_root / rel
        ensure_parent(absolute)
        return rel, absolute
    # Validator guarantees output is @work/ or @outputs.; defensive fail-closed.
    raise workflow_error(f"unresolvable step output target {rejected_value(output)!r}", INVALID_WORKFLOW_SPEC)


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
