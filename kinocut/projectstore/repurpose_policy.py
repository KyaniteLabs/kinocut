"""Evaluate frozen repurpose release policy before a durable job can succeed."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any

from kinocut.engine_repurpose import _release_checkpoint
from kinocut.errors import MCPVideoError
from kinocut.workflow.planner import _hash_if_exists
from kinocut.workflow.spec import load_spec, parse_spec
from . import store
from .render_jobs import get_render_job, job_spec_path


def _unavailable() -> MCPVideoError:
    return MCPVideoError(
        "Repurpose release evidence is missing, changed or inconsistent",
        error_type="quality_error",
        code="repurpose_release_evidence_invalid",
    )


def _relative_evidence(value: Any, project: store.Project) -> Any:
    """Persist project-relative review paths; never serialize absolute host paths."""
    if isinstance(value, dict):
        return {key: _relative_evidence(item, project) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_relative_evidence(item, project) for item in value]
    if isinstance(value, str) and Path(value).is_absolute():
        try:
            return Path(value).resolve().relative_to(project.root.resolve()).as_posix()
        except ValueError:
            raise _unavailable() from None
    return value


def _bound_artifacts(
    project: store.Project, spec_path: Path, declarations: Any, entries: Any, path_key: str, hash_key: str
):
    if not isinstance(entries, list) or len(entries) != len(declarations) or not entries:
        raise _unavailable()
    if any(not isinstance(entry, dict) or not isinstance(entry.get("id"), str) for entry in entries):
        raise _unavailable()
    by_id = {entry.get("id"): entry for entry in entries if isinstance(entry, dict)}
    if len(by_id) != len(entries) or set(by_id) != set(declarations):
        raise _unavailable()
    bound = []
    for output_id, declared in declarations.items():
        entry = by_id[output_id]
        if entry.get(path_key) != declared.path:
            raise _unavailable()
        relative = (spec_path.parent / declared.path).relative_to(project.root)
        path = store.safe_target(project, PurePosixPath(relative.as_posix()))
        digest = _hash_if_exists(path, {})
        if digest is None or entry.get(hash_key) != digest:
            raise _unavailable()
        bound.append((output_id, path, digest))
    return bound


def enforce_repurpose_release_policy(project: store.Project, job_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    """Measure actual receipt-bound outputs; skipped checkpoints disclose the opt-out."""
    head = get_render_job(project, job_id)
    if head.created_by != "tool:repurpose":
        return receipt
    spec_path = job_spec_path(project, job_id)
    if "sha256:" + hashlib.sha256(spec_path.read_bytes()).hexdigest() != head.workflow_spec_digest:
        raise _unavailable()
    spec = parse_spec(load_spec(spec_path))
    policy = spec.repurpose_release_policy
    if policy is None:
        raise _unavailable()
    bound = _bound_artifacts(project, spec_path, spec.outputs, receipt.get("outputs"), "path", "output_hash")
    sources = _bound_artifacts(project, spec_path, spec.sources, receipt.get("sources"), "resolved", "source_hash")
    evidence = {
        "policy": policy.model_dump(mode="json"),
        "status": "not_evaluated",
        "sources": [{"id": source_id, "source_hash": digest} for source_id, _, digest in sources],
        "outputs": [],
    }
    for output_id, path, digest in bound:
        item = {"id": output_id, "output_hash": digest}
        if policy.include_release_checkpoint:
            review_dir = path.parent / "checkpoints" / output_id
            item["release_checkpoint"] = _relative_evidence(
                _release_checkpoint(str(path), str(review_dir), policy.min_score), project
            )
            if _hash_if_exists(path, {}) != digest:
                raise _unavailable()
        evidence["outputs"].append(item)
    if any(_hash_if_exists(path, {}) != digest for _, path, digest in bound + sources):
        raise _unavailable()
    if "sha256:" + hashlib.sha256(spec_path.read_bytes()).hexdigest() != head.workflow_spec_digest:
        raise _unavailable()
    if policy.include_release_checkpoint:
        evidence["status"] = "passed"
    result = dict(receipt)
    result["repurpose_release"] = evidence
    return result
