"""Workflow receipt assembly, atomic writer, error sanitization, and lineage.

Pure data transforms over a validated workflow verdict / completed receipt:
build the §5a receipt dict, write it atomically (stage-then-swap), sanitize
engine faults so no out-of-workspace absolute path leaks into a receipt or MCP
envelope, and derive + attach a validated ``ReceiptLineage``.

This module deliberately depends only on stdlib, the spec/models, planner
helpers, and error codes — never on the executor — so the executor can import
it freely with no circular-import risk. ``attach_receipt_lineage`` and
``_write_receipt`` are re-exported from :mod:`kinocut.workflow.executor` for
existing import sites.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..contracts.trusted_execution import ReceiptLineage
from ..errors import MCPVideoError
from ..ffmpeg_helpers import _validate_artifact_path
from ._errors import (
    INVALID_WORKFLOW_RECEIPT,
    INVALID_WORKFLOW_SPEC,
    WORKFLOW_STEP_FAILED,
    workflow_error,
)
from ._versions import RENDER_DETERMINISM_SCOPE, versions
from .planner import _confine_artifact_path, _hash_if_exists, _probe_source
from .spec import WorkflowStep

_CLEANUP_POLICY_CLEAN = "clean-on-success"
_CLEANUP_POLICY_KEEP = "keep-intermediates"


def _cleanup_policy(keep_intermediates: bool) -> str:
    """Effective cleanup policy string recorded on the receipt (§5a)."""
    return _CLEANUP_POLICY_KEEP if keep_intermediates else _CLEANUP_POLICY_CLEAN


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


def _build_receipt(
    *,
    verdict: dict[str, Any],
    variant: str | None,
    spec_hash: str,
    spec_steps: list[WorkflowStep],
    sources: list[dict[str, Any]],
    steps_receipt: list[dict[str, Any]],
    workspace_root: Path,
    hash_cache: dict[str, str | None],
    run_dir_rel: str,
    intermediates: list[str],
    cleaned: bool,
    keep_intermediates: bool,
    resuming: bool,
    resumed_from: str | None,
    status: str,
) -> dict[str, Any]:
    """Assemble ONE workflow receipt (§5a schema) — the single source of truth.

    Used for both the final terminal receipt and every progressive partial
    receipt written after a completed stage, so a resumed run reads the SAME
    schema/spec_hash/step hashes/work_dir/cleanup semantics/resume cursor it
    would read from the terminal receipt. No second cursor or protocol exists.
    """
    # Progressive (status == "in_progress") receipts are written BEFORE later
    # stages have produced their declared outputs, so ``_hash_if_exists`` would
    # memoize None for those still-absent output paths into the shared
    # ``hash_cache`` — and that None would then be served to the terminal
    # receipt even after the file appears, poisoning the authoritative output
    # hash. Isolate the progressive output hashes in a cache COPY so absent
    # outputs never leak into the shared cache; the terminal receipt keeps
    # using the shared cache unchanged (real hashes only).
    outputs_cache: dict[str, str | None] = hash_cache if status != "in_progress" else dict(hash_cache)
    return {
        "schema_version": 1,
        "receipt_kind": "workflow",
        "tool": "video_workflow_render",
        "versions": versions(),
        "spec_hash": spec_hash,
        "workflow": {"name": verdict["name"], "variant": variant},
        "sources": sources,
        "steps": steps_receipt,
        "outputs": _build_outputs(verdict, workspace_root, outputs_cache),
        "work_dir": run_dir_rel,
        "cleanup_manifest": {
            "intermediates": list(intermediates),
            "cleaned": cleaned,
            "policy": _cleanup_policy(keep_intermediates),
        },
        "resume_cursor": _resume_cursor(steps_receipt),
        "feature_flags": {
            "variants": bool(verdict["variants"]),
            "resume_used": resuming,
            "resumed_from": resumed_from,
            "ops": [step.op for step in spec_steps],
        },
        "warnings": [],
        "status": status,
        "render_determinism_scope": RENDER_DETERMINISM_SCOPE,
    }


# --- Error sanitization ------------------------------------------------------


def _wrap_engine_exception(exc: Exception, step: WorkflowStep, workspace_root: Path) -> MCPVideoError:
    """Wrap an arbitrary engine exception as a fail-closed ``MCPVideoError``.

    Type confusion is caught earlier by param-value validation (S2); this is the
    depth layer for any OTHER runtime fault an engine may raise (RuntimeError,
    AttributeError, ...). The message is sanitized so a receipt or MCP envelope
    never leaks the absolute workspace path OR any other out-of-workspace path.
    """
    message = _sanitize_message(f"step {step.id!r} ({step.op}) failed: {type(exc).__name__}: {exc}", workspace_root)
    return workflow_error(message, WORKFLOW_STEP_FAILED)


def _sanitize_error(exc: MCPVideoError, workspace_root: Path) -> dict[str, Any]:
    """Structured, path-sanitized error record for a failed step."""
    return {
        "code": exc.code,
        "type": exc.error_type,
        "message": _sanitize_message(str(exc), workspace_root),
        "suggested_action": exc.suggested_action,
    }


# Any absolute path token still present AFTER the workspace prefix is stripped is, by
# construction, OUTSIDE the workspace (in-workspace paths are relativized first), so it is
# redacted wholesale — not just home dirs. An engine fault can embed a path anywhere on the
# host (/Users, /home, /opt, /srv, /etc, /tmp, /private/var/folders, /mnt, /data, ...);
# leaving any of them in a receipt or MCP error envelope is an information leak.
_ABSOLUTE_PATH_RE = re.compile(r"/[^\s:'\"/]+(?:/[^\s:'\"/]+)*")
_REDACTED_PATH = "<redacted-path>"


def _sanitize_message(message: str, workspace_root: Path) -> str:
    """Strip the workspace prefix, then redact any residual out-of-workspace absolute path."""
    return _ABSOLUTE_PATH_RE.sub(_REDACTED_PATH, _strip_workspace(message, workspace_root))


def _strip_workspace(message: str, workspace_root: Path) -> str:
    """Drop the absolute workspace prefix so receipts stay workspace-relative."""
    root = str(workspace_root)
    return message.replace(root + os.sep, "").replace(root, "")


def _utcnow() -> str:
    """Current UTC timestamp as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _write_receipt(receipt: dict[str, Any], save_receipt: str, workspace_root: Path | None = None) -> None:
    """Atomically write the receipt as pretty, stable JSON (matches the plan writer).

    Stage-then-swap: serialize to a same-directory temp file, then ``os.replace`` it
    onto the target. ``os.replace`` is atomic on POSIX/Windows for same-filesystem
    renames, and the temp lives next to the target so the existing path-confinement
    guard covers it. A SIGKILL mid-write can therefore never leave a torn receipt —
    a reader (including a resumed run) always sees either the prior complete receipt
    or the new complete receipt, which is what makes kill/reopen/resume safe."""
    if not isinstance(save_receipt, str) or not save_receipt:
        raise workflow_error("save_receipt must be a non-empty file path", INVALID_WORKFLOW_SPEC)
    _validate_artifact_path(save_receipt)  # traversal / symlink / system-dir / dotfile / overwrite-non-json guard
    if workspace_root is not None:
        _confine_artifact_path(save_receipt, workspace_root, "save_receipt")
    payload = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    target = Path(save_receipt)
    tmp = target.parent / f".{target.name}.{uuid.uuid4().hex[:8]}.tmp"
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, target)


# --- Receipt lineage ---------------------------------------------------------


_LINEAGE_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def attach_receipt_lineage(
    receipt: dict[str, Any],
    *,
    edit_project_id: str,
    revision_id: str,
    job_id: str,
    save_receipt: str | None = None,
    workspace_root: Path | None = None,
) -> dict[str, Any]:
    """Derive a validated ``ReceiptLineage`` from a successful receipt and attach it.

    Compact internal helper (NOT part of the public workflow surface): given an
    already-successful workflow receipt plus exact edit-project/revision/job
    identity, it derives ``source_digests`` (each recorded source hash, in spec
    order), ``output_digest`` (the recorded output hash for a single output, else a
    deterministic sha256 over the sorted output hashes), and a canonical
    ``toolchain_fingerprint`` (sha256 over the receipt's
    recorded ``versions``), validates the bundle through ``ReceiptLineage``
    (fail-closed on any missing/malformed hash or invalid identity), attaches a
    ``lineage`` object to the receipt, and — when ``save_receipt`` names the same
    path the receipt was written to — atomically rewrites that file in place.

    Lineage is strictly additive: existing receipt fields (per-step hashes, the
    cleanup manifest, …) are never touched, and a legacy synchronous receipt is
    byte/schema unchanged unless this helper is explicitly called. No lineage
    argument is added to the public ``video_workflow_render`` surface.
    """
    receipt["lineage"] = _derive_receipt_lineage(
        receipt,
        edit_project_id=edit_project_id,
        revision_id=revision_id,
        job_id=job_id,
    )
    if save_receipt is not None:
        _write_receipt(receipt, save_receipt, workspace_root)
    return receipt


def _derive_receipt_lineage(
    receipt: dict[str, Any],
    *,
    edit_project_id: str,
    revision_id: str,
    job_id: str,
) -> dict[str, Any]:
    """Build a validated lineage dict purely from a completed workflow receipt.

    Derivation reads only the receipt's recorded source/output hashes and its
    ``versions`` object — it never re-hashes disk bytes — so lineage is a stable
    function of an already-successful receipt plus its identity.
    """
    if not isinstance(receipt, dict):
        raise workflow_error("lineage requires a workflow receipt", INVALID_WORKFLOW_RECEIPT)
    if receipt.get("status") != "completed":
        raise workflow_error("lineage may only be attached to a completed receipt", INVALID_WORKFLOW_RECEIPT)
    try:
        lineage = ReceiptLineage(
            edit_project_id=edit_project_id,
            revision_id=revision_id,
            job_id=job_id,
            source_digests=_lineage_source_digests(receipt),
            output_digest=_lineage_output_digest(receipt),
            toolchain_fingerprint=_lineage_toolchain_fingerprint(receipt),
        )
    except ValidationError as exc:
        raise workflow_error(f"invalid receipt lineage: {exc}", INVALID_WORKFLOW_RECEIPT) from exc
    data = lineage.model_dump()
    data["source_digests"] = list(data["source_digests"])
    return data


def _lineage_source_digests(receipt: dict[str, Any]) -> list[str]:
    """Each recorded source hash, in spec order; fail-closed on any gap or malformation."""
    sources = receipt.get("sources")
    if not isinstance(sources, list) or not sources:
        raise workflow_error("receipt has no sources for lineage", INVALID_WORKFLOW_RECEIPT)
    digests: list[str] = []
    for entry in sources:
        digest = entry.get("source_hash") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not _LINEAGE_SHA256_RE.match(digest):
            raise workflow_error("receipt source hash missing or malformed for lineage", INVALID_WORKFLOW_RECEIPT)
        digests.append(digest)
    return digests


def _lineage_output_digest(receipt: dict[str, Any]) -> str:
    """The artifact digest when one output; a deterministic aggregate over sorted hashes otherwise.

    Fail-closed on any gap or malformation. A single-output workflow records the
    artifact's own hash directly (the output IS the digest). When a workflow
    declares several outputs the lineage contract still carries a single
    ``output_digest``, so the recorded hashes are sorted then folded into one
    canonical sha256 (order-stable regardless of declaration order).
    """
    outputs = receipt.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise workflow_error("receipt has no outputs for lineage", INVALID_WORKFLOW_RECEIPT)
    hashes: list[str] = []
    for entry in outputs:
        digest = entry.get("output_hash") if isinstance(entry, dict) else None
        if not isinstance(digest, str) or not _LINEAGE_SHA256_RE.match(digest):
            raise workflow_error("receipt output hash missing or malformed for lineage", INVALID_WORKFLOW_RECEIPT)
        hashes.append(digest)
    if len(hashes) == 1:
        return hashes[0]
    encoded = json.dumps(sorted(hashes), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _lineage_toolchain_fingerprint(receipt: dict[str, Any]) -> str:
    """Canonical sha256 over the receipt's recorded ``versions`` object."""
    versions = receipt.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise workflow_error("receipt has no versions for lineage", INVALID_WORKFLOW_RECEIPT)
    encoded = json.dumps(versions, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
