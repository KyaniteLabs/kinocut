"""Sequential render executor + receipt writer for the agent workflow engine.

``render_workflow`` validates a job-spec first (fail-closed), then executes the
allowlisted ops SEQUENTIALLY in spec order via the vetted engine functions bound
in ``ops``. Every consumed input is hashed (real sha256, including @work
intermediates and each element of a multi-input ``merge``), and every produced
output is hashed once the step completes. The run is recorded into a workflow
receipt (``schema_version: 1``, ``receipt_kind: "workflow"``) whose field names
follow the plan's §5a schema.

Intermediates live in a per-invocation ``@work`` directory unique to this run
(keyed by the spec-hash prefix + a run id) so cleanup or a future resume can
never touch another run's files; their stems carry the ``mcp_video_`` prefix for
defensive compatibility with ``video_cleanup``'s guard. On success the
manifest-tracked intermediates inside that dir are removed; on failure they are
kept so Story 4's ``--resume`` can continue. The FIRST step whose engine raises
``MCPVideoError`` aborts the job (fail-closed): the failure is recorded on the
receipt (still written to ``save_receipt`` when provided) and then re-raised so
the surface reports it.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import MCPVideoError
from ._errors import (
    INVALID_WORKFLOW_RECEIPT,
    INVALID_WORKFLOW_SPEC,
    RESUME_SPEC_MISMATCH,
    UNSAFE_WORKFLOW_SOURCE,
    workflow_error,
)
from ._versions import versions
from .inspector import read_receipt
from .ops import OP_ADAPTERS, OpAdapter
from .planner import _hash_if_exists, _iter_step_refs, _probe_source
from .spec import WorkflowStep, load_spec, parse_spec, validate_spec_path
from .validator import validate_workflow_spec

_SOURCE_PREFIX = "@sources."
_WORK_PREFIX = "@work/"
_OUTPUT_PREFIX = "@outputs."
_WORK_STEM_PREFIX = "mcp_video_"
_RENDER_DETERMINISM_SCOPE = (
    "spec/input/output hashes are deterministic; rendered bytes may vary across FFmpeg builds"
)
_CLEANUP_POLICY = "clean-on-success"


def render_workflow(
    spec_path: str, resume_receipt: str | None = None, save_receipt: str | None = None
) -> dict[str, Any]:
    """Execute a validated workflow job-spec sequentially and return the receipt.

    Validates ``spec_path`` first (fail-closed via the structural validator),
    then runs each allowlisted op in spec order via its engine binding, hashing
    every consumed input and each produced output. Intermediates are written to
    a per-invocation ``@work`` directory and cleaned on success (kept on
    failure). Optionally writes the receipt JSON to ``save_receipt``.

    ``resume_receipt`` is a prior render receipt (from a job that failed with its
    intermediates kept). Resume is fail-closed per §5a: the current ``spec_hash``
    MUST equal the receipt's or it is a different job (``resume_spec_mismatch``).
    A step is SKIPPED (reused) iff its prior status is ``completed`` AND its
    recorded input hashes still match the current inputs AND (for output-producing
    ops) its recorded output file still exists and re-hashes to the recorded
    ``output_hash``. These are INTEGRITY checks on persisted intermediates, never
    determinism claims. The FIRST step failing any check is the resume point; it
    and every step after it re-run. The prior run's ``@work`` directory is reused
    so kept intermediates are found (a missing dir/file simply fails the checks
    and re-runs — that IS the mechanism).

    Fail-closed: the first step whose engine raises ``MCPVideoError`` aborts the
    job; the failure is recorded on the receipt (which is still written to
    ``save_receipt`` when provided) and then re-raised.
    """
    verdict = validate_workflow_spec(spec_path)
    resolved = validate_spec_path(spec_path)
    spec = parse_spec(load_spec(resolved))  # real param/input VALUES (verdict carries only names)
    workspace_root = Path(os.path.realpath(resolved.parent))
    spec_hash = "sha256:" + hashlib.sha256(resolved.read_bytes()).hexdigest()

    source_paths: dict[str, str] = verdict["source_paths"]
    output_paths: dict[str, str] = verdict["output_paths"]

    resuming = resume_receipt is not None
    if resuming:
        prior_by_id, run_dir_rel, run_dir_abs = _load_resume(resume_receipt, spec_hash, workspace_root)
    else:
        prior_by_id = {}
        run_dir_rel, run_dir_abs = _make_run_dir(workspace_root, spec_hash)

    hash_cache: dict[str, str | None] = {}
    work_paths: dict[str, Path] = {}  # @work name -> absolute path on disk
    sources = _build_sources(verdict, workspace_root, hash_cache)

    steps_receipt: list[dict[str, Any]] = []
    intermediates: list[str] = []
    failure: MCPVideoError | None = None
    failed_index = -1
    still_reusing = resuming
    resumed_from: str | None = None

    for index, step in enumerate(spec.steps):
        adapter = OP_ADAPTERS[step.op]
        output_rel, output_abs = _resolve_output(
            step.output, workspace_root, run_dir_rel, run_dir_abs, output_paths, work_paths
        )
        input_hashes = _hash_inputs(step.inputs, workspace_root, source_paths, work_paths, hash_cache)

        if still_reusing and _step_reusable(prior_by_id.get(step.id), adapter, input_hashes, output_abs, hash_cache):
            prior = prior_by_id[step.id]
            output_hash = _hash_if_exists(output_abs, hash_cache) if output_abs is not None else None
            if output_rel is not None and output_rel.startswith(run_dir_rel + "/"):
                intermediates.append(output_rel)
            steps_receipt.append(
                _step_entry(
                    step, "completed", input_hashes, output_rel, output_hash,
                    prior.get("started_at"), prior.get("ended_at"), skipped=True,
                )
            )
            continue

        if still_reusing:  # first step that could not be reused = the resume point
            still_reusing = False
            resumed_from = step.id

        started_at = _utcnow()
        try:
            _run_step(adapter, step, workspace_root, source_paths, work_paths, output_abs)
        except MCPVideoError as exc:
            steps_receipt.append(
                _step_entry(
                    step, "failed", input_hashes, output_rel, None, started_at, _utcnow(),
                    error=_sanitize_error(exc, workspace_root),
                )
            )
            failure = exc
            failed_index = index
            break
        output_hash = _hash_if_exists(output_abs, hash_cache) if output_abs is not None else None
        if output_rel is not None and output_rel.startswith(run_dir_rel + "/"):
            intermediates.append(output_rel)
        steps_receipt.append(
            _step_entry(step, "completed", input_hashes, output_rel, output_hash, started_at, _utcnow())
        )

    if failure is not None:
        for step in spec.steps[failed_index + 1 :]:
            steps_receipt.append(_step_entry(step, "pending", {}, step.output, None, None, None))

    cleaned = _apply_cleanup(run_dir_abs, intermediates, workspace_root, success=failure is None)
    outputs = _build_outputs(verdict, workspace_root, hash_cache)

    receipt = {
        "schema_version": 1,
        "receipt_kind": "workflow",
        "tool": "video_workflow_render",
        "versions": versions(),
        "spec_hash": spec_hash,
        "workflow": {"name": verdict["name"], "variant": None},
        "sources": sources,
        "steps": steps_receipt,
        "outputs": outputs,
        "work_dir": run_dir_rel,
        "cleanup_manifest": {
            "intermediates": intermediates,
            "cleaned": cleaned,
            "policy": _CLEANUP_POLICY,
        },
        "resume_cursor": _resume_cursor(steps_receipt),
        "feature_flags": {
            "variants": bool(verdict["variants"]),
            "resume_used": resuming,
            "resumed_from": resumed_from,
            "ops": [step.op for step in spec.steps],
        },
        "warnings": [],
        "status": "failed" if failure is not None else "completed",
        "render_determinism_scope": _RENDER_DETERMINISM_SCOPE,
    }

    if save_receipt is not None:
        _write_receipt(receipt, save_receipt)

    if failure is not None:
        raise failure

    return receipt


# --- Resume ------------------------------------------------------------------


def _load_resume(
    resume_receipt: str, spec_hash: str, workspace_root: Path
) -> tuple[dict[str, dict[str, Any]], str, Path]:
    """Load + gate a prior receipt for resume (fail-closed per §5a).

    Enforces the spec_hash gate (a changed spec is a different job) and reuses the
    prior run's ``@work`` directory so kept intermediates are found. Returns
    ``(prior_steps_by_id, work_dir_rel, work_dir_abs)``.
    """
    prior = read_receipt(resume_receipt)  # raises invalid_workflow_receipt on unreadable/malformed JSON
    prior_hash = prior.get("spec_hash")
    if prior_hash != spec_hash:
        raise workflow_error(
            f"resume receipt spec_hash {prior_hash!r} does not match the current spec_hash {spec_hash!r}; "
            "this is a different job",
            RESUME_SPEC_MISMATCH,
        )
    prior_steps = prior.get("steps")
    if not isinstance(prior_steps, list):
        raise workflow_error("resume receipt has no step list to resume from", INVALID_WORKFLOW_RECEIPT)
    prior_by_id = {s["id"]: s for s in prior_steps if isinstance(s, dict) and s.get("id")}
    work_dir_rel = prior.get("work_dir")
    if not isinstance(work_dir_rel, str) or not work_dir_rel:
        raise workflow_error("resume receipt is missing the work_dir to resume into", INVALID_WORKFLOW_RECEIPT)
    run_dir_abs = Path(os.path.realpath(workspace_root / work_dir_rel))
    try:
        run_dir_abs.relative_to(workspace_root)
    except ValueError:
        raise workflow_error(
            "resume receipt work_dir escapes the workspace root", UNSAFE_WORKFLOW_SOURCE
        ) from None
    run_dir_abs.mkdir(parents=True, exist_ok=True)  # recreated if the prior dir was deleted (steps then re-run)
    return prior_by_id, work_dir_rel, run_dir_abs


def _step_reusable(
    prior: dict[str, Any] | None,
    adapter: OpAdapter,
    current_input_hashes: dict[str, str | None],
    output_abs: Path | None,
    hash_cache: dict[str, str | None],
) -> bool:
    """Skip-iff gate (§5a.2): reuse a step only when its product is still valid.

    ALL must hold: the prior step was ``completed`` AND its recorded input hashes
    still match the current inputs AND — for output-producing ops — its recorded
    output file still exists and re-hashes to the recorded ``output_hash``.
    Inspection ops (e.g. ``probe``) persist no output file, so they are reusable
    on an input-hash match alone. Any mismatch (tampered/absent intermediate,
    changed input) fails the gate so the step re-runs.
    """
    if prior is None or prior.get("status") != "completed":
        return False
    if prior.get("input_hashes") != current_input_hashes:
        return False
    if not adapter.has_output:
        return True
    if output_abs is None or not output_abs.is_file():
        return False
    current = _hash_if_exists(output_abs, hash_cache)
    return current is not None and current == prior.get("output_hash")


# --- Step execution ----------------------------------------------------------


def _run_step(
    adapter: OpAdapter,
    step: WorkflowStep,
    workspace_root: Path,
    source_paths: dict[str, str],
    work_paths: dict[str, Path],
    output_abs: Path | None,
) -> None:
    """Invoke the backing engine function for one step (fail-closed)."""
    resolved_input = _resolve_engine_input(adapter, step.inputs, workspace_root, source_paths, work_paths)
    kwargs: dict[str, Any] = dict(step.params)
    kwargs[adapter.engine_input_param] = resolved_input
    if adapter.has_output:
        kwargs["output_path"] = str(output_abs)
    adapter.engine_fn(**kwargs)


def _resolve_engine_input(
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
    if ref.startswith(_SOURCE_PREFIX):
        return workspace_root / source_paths[ref[len(_SOURCE_PREFIX) :]]
    if ref.startswith(_WORK_PREFIX):
        name = ref[len(_WORK_PREFIX) :]
        path = work_paths.get(name)
        if path is None:  # defensive: validator guarantees backward production
            raise workflow_error(
                f"internal: @work ref {ref!r} was not produced by an earlier step", INVALID_WORKFLOW_SPEC
            )
        return path
    return workspace_root / ref


def _hash_inputs(
    inputs: dict[str, Any],
    workspace_root: Path,
    source_paths: dict[str, str],
    work_paths: dict[str, Path],
    hash_cache: dict[str, str | None],
) -> dict[str, str | None]:
    """Real sha256 for every consumed input (``src`` / ``srcs[i]`` slots)."""
    hashes: dict[str, str | None] = {}
    for key, ref in _iter_step_refs(inputs):
        path = _resolve_ref_path(ref, workspace_root, source_paths, work_paths)
        hashes[key] = _hash_if_exists(path, hash_cache)
    return hashes


# --- @work directory + output resolution -------------------------------------


def _make_run_dir(workspace_root: Path, spec_hash: str) -> tuple[str, Path]:
    """Create a unique per-run @work directory (spec-hash prefix + run id)."""
    prefix = spec_hash.split(":", 1)[-1][:8]
    run_id = uuid.uuid4().hex[:8]
    rel = f"work/{prefix}-{run_id}"
    absolute = workspace_root / rel
    absolute.mkdir(parents=True, exist_ok=True)
    return rel, absolute


def _resolve_output(
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
    if output.startswith(_WORK_PREFIX):
        name = output[len(_WORK_PREFIX) :]
        filename = _WORK_STEM_PREFIX + name.replace("/", "_").replace("\\", "_")
        absolute = run_dir_abs / filename
        _ensure_parent(absolute)
        work_paths[name] = absolute
        return f"{run_dir_rel}/{filename}", absolute
    if output.startswith(_OUTPUT_PREFIX):
        rel = output_paths[output[len(_OUTPUT_PREFIX) :]]
        absolute = workspace_root / rel
        _ensure_parent(absolute)
        return rel, absolute
    # Validator guarantees output is @work/ or @outputs.; defensive fail-closed.
    raise workflow_error(f"unresolvable step output target {output!r}", INVALID_WORKFLOW_SPEC)


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# --- Cleanup -----------------------------------------------------------------


def _apply_cleanup(
    run_dir_abs: Path, intermediates: list[str], workspace_root: Path, *, success: bool
) -> bool:
    """Remove manifest-tracked intermediates on success; keep on failure.

    Only ever deletes files that resolve inside THIS run's @work directory.
    """
    if not success:
        return False
    run_real = Path(os.path.realpath(run_dir_abs))
    for rel in intermediates:
        real = Path(os.path.realpath(workspace_root / rel))
        try:
            real.relative_to(run_real)
        except ValueError:
            continue  # refuse to delete anything outside the run dir
        if real.is_file():
            real.unlink()
    with contextlib.suppress(OSError):  # best-effort tidy of the now-empty run dir
        run_real.rmdir()
    return True


# --- Receipt assembly --------------------------------------------------------


def _build_sources(
    verdict: dict[str, Any], workspace_root: Path, hash_cache: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Per-source receipt entries: resolved path, real source hash, probe."""
    source_paths: dict[str, str] = verdict["source_paths"]
    entries: list[dict[str, Any]] = []
    for source_id in verdict["sources"]:
        rel = source_paths[source_id]
        absolute = workspace_root / rel
        entries.append(
            {
                "id": source_id,
                "resolved": rel,
                "source_hash": _hash_if_exists(absolute, hash_cache),
                "probe": _probe_source(absolute) if absolute.exists() else None,
            }
        )
    return entries


def _build_outputs(
    verdict: dict[str, Any], workspace_root: Path, hash_cache: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Final declared outputs with their post-render hashes."""
    output_paths: dict[str, str] = verdict["output_paths"]
    return [
        {
            "id": output_id,
            "path": output_paths[output_id],
            "output_hash": _hash_if_exists(workspace_root / output_paths[output_id], hash_cache),
        }
        for output_id in verdict["outputs"]
    ]


def _step_entry(
    step: WorkflowStep,
    status: str,
    input_hashes: dict[str, str | None],
    output: str | None,
    output_hash: str | None,
    started_at: str | None,
    ended_at: str | None,
    *,
    error: dict[str, Any] | None = None,
    skipped: bool = False,
) -> dict[str, Any]:
    """Build one receipt step entry.

    Adds ``error`` only for a failed step and ``skipped: true`` only for a step
    reused on resume (its status stays ``completed`` per §5a); a normal render
    emits neither key, so the Story-3 step-field set is unchanged.
    """
    entry: dict[str, Any] = {
        "id": step.id,
        "op": step.op,
        "status": status,
        "inputs": step.inputs,
        "input_hashes": input_hashes,
        "output": output,
        "output_hash": output_hash,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    if error is not None:
        entry["error"] = error
    if skipped:
        entry["skipped"] = True
    return entry


def _resume_cursor(steps: list[dict[str, Any]]) -> dict[str, str | None]:
    """Last completed step + the next step to run (the resume point on failure)."""
    last_completed: str | None = None
    next_step: str | None = None
    for step in steps:
        if step["status"] == "completed":
            last_completed = step["id"]
        elif next_step is None and step["status"] in ("failed", "pending"):
            next_step = step["id"]
    return {"last_completed_step": last_completed, "next_step": next_step}


def _sanitize_error(exc: MCPVideoError, workspace_root: Path) -> dict[str, Any]:
    """Structured, path-sanitized error record for a failed step."""
    return {
        "code": exc.code,
        "type": exc.error_type,
        "message": _strip_workspace(str(exc), workspace_root),
        "suggested_action": exc.suggested_action,
    }


def _strip_workspace(message: str, workspace_root: Path) -> str:
    """Drop the absolute workspace prefix so receipts stay workspace-relative."""
    root = str(workspace_root)
    return message.replace(root + os.sep, "").replace(root, "")


def _utcnow() -> str:
    """Current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _write_receipt(receipt: dict[str, Any], save_receipt: str) -> None:
    """Write the receipt as pretty, stable JSON (matches the plan writer)."""
    if not isinstance(save_receipt, str) or not save_receipt:
        raise workflow_error("save_receipt must be a non-empty file path", INVALID_WORKFLOW_SPEC)
    if "\x00" in save_receipt:
        raise workflow_error("save_receipt path contains null bytes", INVALID_WORKFLOW_SPEC)
    Path(save_receipt).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
