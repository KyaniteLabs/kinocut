"""Legacy-tolerant receipt inspector for the agent workflow engine.

``inspect_receipt`` reads ANY receipt this project emits — a workflow render
receipt (``receipt_kind: "workflow"``), a dry-run plan artifact
(``workflow_plan``), or a ``layer_plan`` receipt (v1 legacy with NO
``receipt_kind`` field, or v2 with the discriminator) — and returns a single
NORMALIZED inspection: kind, schema_version, tool, versions, a status summary,
a read-only hash presence/integrity report, outputs, warnings, and cleanup
state, plus human-review pointers and known limitations.

Legacy tolerance (§5d): a receipt with no ``receipt_kind`` has its kind INFERRED
from the ``tool`` field (``video_composite_layers`` -> ``layer_plan``,
``video_workflow_render`` -> ``workflow``, ``video_workflow_plan`` ->
``workflow_plan``); a receipt with neither defaults to ``layer_plan``. The kind
is never hardcoded to a schema_version, so a future ``layer_plan`` v2 bump is
handled gracefully.

The integrity report re-hashes the persisted files a receipt names (declared
sources/masks, step outputs, final outputs) and reports which recorded hashes
still match the bytes on disk NOW. It is a READ-ONLY mirror of resume's
integrity gate — never a determinism claim. Recorded paths are resolved relative
to the receipt file's own directory (the presumed workspace root). Any
unreadable/malformed receipt fails closed with ``invalid_workflow_receipt``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ._errors import INVALID_WORKFLOW_RECEIPT, workflow_error
from .planner import _hash_if_exists
from .spec import validate_spec_path

_KIND_BY_TOOL = {
    "video_composite_layers": "layer_plan",
    "video_workflow_render": "workflow",
    "video_workflow_plan": "workflow_plan",
}
_DEFAULT_KIND = "layer_plan"  # §5d: a receipt_kind-less, tool-less receipt defaults to layer_plan


def read_receipt(receipt_path: str) -> dict[str, Any]:
    """Read + JSON-decode a receipt file into a dict (fail-closed).

    Shared by ``inspect_receipt`` and the executor's resume path so both treat an
    unreadable/malformed/non-object receipt identically (``invalid_workflow_receipt``).
    """
    resolved = validate_spec_path(receipt_path)  # existing .json path, workspace-safe, no null bytes
    try:
        data = json.loads(resolved.read_bytes().decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise workflow_error(f"unreadable workflow receipt: {exc}", INVALID_WORKFLOW_RECEIPT) from None
    if not isinstance(data, dict):
        raise workflow_error("workflow receipt must be a JSON object", INVALID_WORKFLOW_RECEIPT)
    return data


def inspect_receipt(receipt_path: str) -> dict[str, Any]:
    """Normalize + integrity-check any project receipt (read-only, fail-closed)."""
    receipt = read_receipt(receipt_path)
    base_dir = Path(validate_spec_path(receipt_path)).parent
    kind, kind_inferred = _resolve_kind(receipt)
    hash_cache: dict[str, str | None] = {}

    if kind == "layer_plan":
        status, integrity, outputs = _inspect_layer_plan(receipt, base_dir, hash_cache)
    elif kind == "workflow_plan":
        status, integrity, outputs = _inspect_workflow(receipt, base_dir, hash_cache, planned=True)
    else:  # "workflow" (or any workflow-shaped kind)
        status, integrity, outputs = _inspect_workflow(receipt, base_dir, hash_cache, planned=False)

    feature_flags = receipt.get("feature_flags") if isinstance(receipt.get("feature_flags"), dict) else {}
    resume = None
    if kind in ("workflow", "workflow_plan"):
        resume = {
            "resume_cursor": receipt.get("resume_cursor"),
            "resume_used": bool(feature_flags.get("resume_used", False)),
            "resumed_from": feature_flags.get("resumed_from"),
        }

    return {
        "kind": kind,
        "schema_version": receipt.get("schema_version"),
        "tool": receipt.get("tool"),
        "versions": receipt.get("versions"),
        "spec_hash": receipt.get("spec_hash"),
        "workflow": receipt.get("workflow"),
        "status": status,
        "integrity": integrity,
        "outputs": outputs,
        "warnings": receipt.get("warnings") if isinstance(receipt.get("warnings"), list) else [],
        "cleanup": receipt.get("cleanup_manifest"),
        "resume": resume,
        "human_review": _human_review(kind, kind_inferred, status, integrity),
        "known_limitations": _known_limitations(kind),
    }


# --- Kind inference (§5d) ----------------------------------------------------


def _resolve_kind(receipt: dict[str, Any]) -> tuple[str, bool]:
    """Return (kind, inferred) — inferred is True when no ``receipt_kind`` was present."""
    declared = receipt.get("receipt_kind")
    if isinstance(declared, str) and declared:
        return declared, False
    tool = receipt.get("tool")
    if isinstance(tool, str) and tool in _KIND_BY_TOOL:
        return _KIND_BY_TOOL[tool], True
    return _DEFAULT_KIND, True


# --- Per-kind normalization --------------------------------------------------


def _inspect_workflow(
    receipt: dict[str, Any], base_dir: Path, hash_cache: dict[str, str | None], *, planned: bool
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Normalize a workflow render receipt or a dry-run plan artifact."""
    raw_steps = receipt.get("steps") if isinstance(receipt.get("steps"), list) else []
    steps: list[dict[str, Any]] = []
    failed_step: str | None = None
    error: Any = None
    for raw in raw_steps:
        if not isinstance(raw, dict):
            continue
        entry = {"id": raw.get("id"), "op": raw.get("op"), "status": raw.get("status")}
        if raw.get("skipped"):
            entry["skipped"] = True
        if raw.get("status") == "failed":
            failed_step = raw.get("id")
            error = raw.get("error")
            entry["error"] = raw.get("error")
        steps.append(entry)

    overall = "planned" if planned else receipt.get("status")
    status = {"overall": overall, "steps": steps, "failed_step": failed_step, "error": error}

    cleaned_paths = _cleaned_intermediates(receipt)  # intentionally-removed @work files are not "missing"
    source_entries = [
        _integrity_entry(src.get("id"), src.get("resolved"), src.get("source_hash"), base_dir, hash_cache)
        for src in receipt.get("sources", [])
        if isinstance(src, dict)
    ]
    step_output_entries = [
        _integrity_entry(raw.get("id"), raw.get("output"), raw.get("output_hash"), base_dir, hash_cache, cleaned_paths)
        for raw in raw_steps
        if isinstance(raw, dict) and raw.get("output")
    ]
    output_entries = [
        _integrity_entry(out.get("id"), out.get("path"), out.get("output_hash"), base_dir, hash_cache)
        for out in receipt.get("outputs", [])
        if isinstance(out, dict)
    ]
    integrity = _integrity_report(source_entries, step_output_entries, output_entries)
    outputs = [
        {"id": out.get("id"), "path": out.get("path"), "output_hash": out.get("output_hash")}
        for out in receipt.get("outputs", [])
        if isinstance(out, dict)
    ]
    return status, integrity, outputs


def _inspect_layer_plan(
    receipt: dict[str, Any], base_dir: Path, hash_cache: dict[str, str | None]
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    """Normalize a layer_plan receipt (v1 legacy or v2), a single-render artifact."""
    output_path = receipt.get("output_path")
    output_hash = receipt.get("output_hash")
    overall = "rendered" if output_hash else "planned"
    status = {"overall": overall, "steps": [], "failed_step": None, "error": None}

    source_entries: list[dict[str, Any]] = []
    for layer in receipt.get("layers", []):
        if not isinstance(layer, dict):
            continue
        source_entries.append(
            _integrity_entry(layer.get("id"), layer.get("resolved_src"), layer.get("source_hash"), base_dir, hash_cache)
        )
        if layer.get("mask"):
            source_entries.append(
                _integrity_entry(
                    f"{layer.get('id')}:mask", layer.get("mask"), layer.get("mask_hash"), base_dir, hash_cache
                )
            )
    output_entries = [_integrity_entry(None, output_path, output_hash, base_dir, hash_cache)] if output_path else []
    integrity = _integrity_report(source_entries, [], output_entries)
    outputs = [{"id": None, "path": output_path, "output_hash": output_hash}] if output_path else []
    return status, integrity, outputs


# --- Integrity report --------------------------------------------------------


def _cleaned_intermediates(receipt: dict[str, Any]) -> frozenset[str]:
    """Paths a successful run intentionally removed (so they read as ``cleaned``, not ``missing``)."""
    manifest = receipt.get("cleanup_manifest")
    if not isinstance(manifest, dict) or not manifest.get("cleaned"):
        return frozenset()
    intermediates = manifest.get("intermediates")
    return frozenset(p for p in intermediates if isinstance(p, str)) if isinstance(intermediates, list) else frozenset()


def _integrity_entry(
    identifier: Any,
    path: Any,
    recorded_hash: Any,
    base_dir: Path,
    hash_cache: dict[str, str | None],
    cleaned_paths: frozenset[str] = frozenset(),
) -> dict[str, Any]:
    """One read-only integrity row: recorded hash vs the file's current hash.

    A file recorded as an intentionally-cleaned intermediate reads as ``cleaned``
    (expected) rather than ``missing`` (an alarm) when it is absent.
    """
    current_hash: str | None = None
    if isinstance(path, str) and path:
        candidate = Path(path)
        absolute = candidate if candidate.is_absolute() else base_dir / candidate
        current_hash = _hash_if_exists(absolute, hash_cache)
    if recorded_hash is None:
        state = "no_recorded_hash"
    elif current_hash is None:
        state = "cleaned" if isinstance(path, str) and path in cleaned_paths else "missing"
    elif current_hash == recorded_hash:
        state = "match"
    else:
        state = "mismatch"
    return {
        "id": identifier,
        "path": path,
        "recorded_hash": recorded_hash,
        "current_hash": current_hash,
        "matches": state == "match",
        "state": state,
    }


def _integrity_report(
    sources: list[dict[str, Any]], step_outputs: list[dict[str, Any]], outputs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Group integrity rows and summarize match/mismatch/missing/cleaned counts."""
    everything = sources + step_outputs + outputs
    checked = [row for row in everything if row["recorded_hash"] is not None]
    return {
        "sources": sources,
        "step_outputs": step_outputs,
        "outputs": outputs,
        "summary": {
            "checked": len(checked),
            "matched": sum(1 for row in checked if row["state"] == "match"),
            "mismatched": sum(1 for row in checked if row["state"] == "mismatch"),
            "missing": sum(1 for row in checked if row["state"] == "missing"),
            "cleaned": sum(1 for row in checked if row["state"] == "cleaned"),
        },
    }


# --- Human review + known limitations ----------------------------------------


def _human_review(kind: str, kind_inferred: bool, status: dict[str, Any], integrity: dict[str, Any]) -> list[str]:
    """Pointers an agent/human should verify before trusting this receipt."""
    notes: list[str] = []
    if kind_inferred:
        notes.append(
            f"receipt had no receipt_kind; kind inferred as {kind!r} (legacy tolerance) — confirm it is correct."
        )
    if status.get("failed_step"):
        notes.append(f"step {status['failed_step']!r} failed; the job did not complete.")
    summary = integrity["summary"]
    if summary["mismatched"]:
        notes.append(
            f"{summary['mismatched']} recorded hash(es) no longer match the bytes on disk; "
            "a persisted file may have been modified since the run."
        )
    if summary["missing"]:
        notes.append(f"{summary['missing']} recorded file(s) with a hash are no longer present on disk.")
    return notes


def _known_limitations(kind: str) -> list[str]:
    """Standing caveats that apply to every inspection of this kind."""
    limits = [
        "Hashes verify persisted file integrity, not render byte-determinism across FFmpeg builds.",
        "Integrity is re-checked against files resolved relative to the receipt's directory; "
        "a receipt moved away from its workspace cannot be integrity-verified.",
    ]
    if kind == "workflow":
        limits.append(
            "Per-step input_hashes reference declared sources or earlier step outputs, which are integrity-checked "
            "under integrity.sources / integrity.step_outputs."
        )
    if kind == "workflow_plan":
        limits.append("This is a dry-run plan artifact; no media was rendered, so output hashes are null.")
    if kind == "layer_plan":
        limits.append("layer_plan receipts carry no per-step status, resume cursor, or tool/ffmpeg versions.")
    return limits
