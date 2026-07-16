"""Focused tests for the optional workflow receipt ``lineage`` attachment (G011).

``attach_receipt_lineage`` is a compact internal helper that takes an
already-successful workflow receipt plus exact edit-project/revision/job
identity, derives the ``ReceiptLineage`` digests purely from the receipt's
recorded source/output hashes and ``versions``, validates the bundle through the
frozen Phase-1 contract, attaches a ``lineage`` object, and atomically rewrites
the same receipt path when requested. It is strictly additive and opt-in: the
public ``video_workflow_render`` surface gains no lineage argument, and a legacy
synchronous receipt stays byte/schema unchanged unless the helper is called.

These tests cover: exact lineage fields, deterministic derivation, the legacy
unchanged contract, invalid identity/hash failure (fail-closed), a persisted
enriched receipt, and the detached runner attaching lineage from the persisted
job identity.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    create_edit_project,
    append_revision,
    get_render_job,
    open_project,
    submit_render_job,
)
from kinocut.projectstore import render_jobs
from kinocut.projectstore import render_runner
from kinocut.server_tools_workflow import video_workflow_render
from kinocut.workflow import render_workflow
from kinocut.workflow.executor import attach_receipt_lineage

EDIT_PROJECT_ID = "edit_project:" + "a" * 64
REVISION_ID = "sha256:" + "b" * 64
JOB_ID = "job:" + "c" * 64
SRC_HASH = "sha256:" + "1" * 64
OUT_HASH = "sha256:" + "2" * 64
EXTRA_OUT_HASH = "sha256:" + "3" * 64


def _completed_receipt(*, extra_output: bool = False) -> dict:
    """A realistic completed workflow receipt (mirrors the engine's §5a schema)."""
    outputs = [{"id": "out1", "path": "out.mp4", "output_hash": OUT_HASH}]
    if extra_output:
        outputs.append({"id": "out2", "path": "out2.mp4", "output_hash": EXTRA_OUT_HASH})
    return {
        "schema_version": 1,
        "receipt_kind": "workflow",
        "tool": "video_workflow_render",
        "versions": {"mcp_video": "1.8.0", "ffmpeg": "7.1.1"},
        "spec_hash": "sha256:" + "d" * 64,
        "workflow": {"name": "demo", "variant": None},
        "sources": [{"id": "src1", "resolved": "in.mp4", "source_hash": SRC_HASH, "probe": None}],
        "steps": [
            {
                "id": "s1",
                "op": "convert",
                "status": "completed",
                "inputs": {"src": "@sources.src1"},
                "input_hashes": {"src": SRC_HASH},
                "output": "@outputs.out1",
                "output_hash": OUT_HASH,
                "started_at": "2026-07-16T00:00:00+00:00",
                "ended_at": "2026-07-16T00:00:01+00:00",
            }
        ],
        "outputs": outputs,
        "work_dir": "@work/mcp_video_run",
        "cleanup_manifest": {"intermediates": [], "cleaned": True, "policy": "clean-on-success"},
        "resume_cursor": {"last_completed_step": "s1", "next_step": None},
        "feature_flags": {"variants": False, "resume_used": False, "resumed_from": None, "ops": ["convert"]},
        "warnings": [],
        "status": "completed",
        "render_determinism_scope": "spec/input/output hashes are deterministic",
    }


def _expected_multi_output_digest(hashes: list[str]) -> str:
    """Deterministic sha256 over SORTED output hashes (mirrors the multi-output derivation)."""
    encoded = json.dumps(sorted(hashes), separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _expected_toolchain_fingerprint(versions: dict) -> str:
    encoded = json.dumps(versions, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# --- exact fields + deterministic derivation ---------------------------------


def test_lineage_has_exact_fields():
    receipt = _completed_receipt()
    out = attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    lineage = out["lineage"]
    assert set(lineage) == {
        "edit_project_id",
        "revision_id",
        "job_id",
        "source_digests",
        "output_digest",
        "toolchain_fingerprint",
    }
    assert lineage["edit_project_id"] == EDIT_PROJECT_ID
    assert lineage["revision_id"] == REVISION_ID
    assert lineage["job_id"] == JOB_ID
    assert lineage["source_digests"] == [SRC_HASH]
    assert lineage["output_digest"] == OUT_HASH  # single output: the artifact digest, not a fold
    assert lineage["toolchain_fingerprint"] == _expected_toolchain_fingerprint(
        {"mcp_video": "1.8.0", "ffmpeg": "7.1.1"}
    )


def test_lineage_derivation_is_deterministic():
    a = attach_receipt_lineage(
        _completed_receipt(), edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID
    )
    b = attach_receipt_lineage(
        _completed_receipt(), edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID
    )
    assert a["lineage"] == b["lineage"]
    # identity participates: a different job_id yields a different lineage bundle
    c = attach_receipt_lineage(
        _completed_receipt(), edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id="job:" + "e" * 64
    )
    assert c["lineage"]["job_id"] != b["lineage"]["job_id"]
    assert c["lineage"]["output_digest"] == b["lineage"]["output_digest"]  # receipt-driven digest unchanged


def test_lineage_folds_multiple_outputs_into_single_digest():
    receipt = _completed_receipt(extra_output=True)
    out = attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    assert out["lineage"]["output_digest"] == _expected_multi_output_digest([OUT_HASH, EXTRA_OUT_HASH])
    assert out["lineage"]["source_digests"] == [SRC_HASH]


def test_single_output_digest_is_the_artifact_hash():
    """For exactly one output the lineage digest IS the recorded artifact hash, not a fold of it."""
    receipt = _completed_receipt()
    out = attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    assert out["lineage"]["output_digest"] == OUT_HASH
    assert out["lineage"]["output_digest"] == receipt["outputs"][0]["output_hash"]


def test_multi_output_digest_is_order_stable():
    """The multi-output digest is a fixed function of the output HASH SET, not declaration order."""
    base = dict(edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    forward = _completed_receipt(extra_output=True)
    reversed_receipt = _completed_receipt(extra_output=True)
    reversed_receipt["outputs"] = [
        {"id": "out2", "path": "out2.mp4", "output_hash": EXTRA_OUT_HASH},
        {"id": "out1", "path": "out.mp4", "output_hash": OUT_HASH},
    ]
    forward_digest = attach_receipt_lineage(forward, **base)["lineage"]["output_digest"]
    reversed_digest = attach_receipt_lineage(reversed_receipt, **base)["lineage"]["output_digest"]
    assert forward_digest == reversed_digest == _expected_multi_output_digest([OUT_HASH, EXTRA_OUT_HASH])
    # a fold over several outputs is never equal to any single artifact hash
    assert forward_digest not in {OUT_HASH, EXTRA_OUT_HASH}


# --- legacy unchanged contract -----------------------------------------------


def test_public_surface_has_no_lineage_argument():
    for fn in (video_workflow_render, render_workflow):
        assert "lineage" not in inspect.signature(fn).parameters


def test_receipt_unchanged_until_helper_called():
    receipt = _completed_receipt()
    snapshot = copy.deepcopy(receipt)
    assert "lineage" not in receipt  # engine never emits lineage
    attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    assert "lineage" in receipt  # helper is the only path that adds it
    # every pre-existing field is byte-identical (per-step hashes, cleanup manifest, ...)
    assert all(receipt[key] == snapshot[key] for key in snapshot)


def test_legacy_synchronous_path_emits_no_lineage():
    """The synchronous engine path never attaches lineage; only the detached runner does.

    A legacy synchronous receipt (the §5a engine schema) carries no ``lineage``
    field, the public surface gains no lineage argument, and lineage appears only
    when the internal helper is explicitly invoked — so the fail-closed change in
    the detached runner leaves the synchronous contract byte/schema unchanged.
    """
    receipt = _completed_receipt()
    assert "lineage" not in receipt  # the engine schema carries no lineage field
    for fn in (video_workflow_render, render_workflow):
        assert "lineage" not in inspect.signature(fn).parameters  # public surface unchanged
    attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    assert "lineage" in receipt  # lineage is opt-in via the helper only


# --- invalid identity / hash failure (fail-closed) ---------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"edit_project_id": "not-an-edit-project"},
        {"revision_id": "not-sha256"},
        {"job_id": "job:tooshort"},
    ],
)
def test_invalid_identity_raises(overrides):
    kwargs = dict(edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    kwargs.update(overrides)
    with pytest.raises(MCPVideoError):
        attach_receipt_lineage(_completed_receipt(), **kwargs)


def test_missing_or_malformed_hash_raises():
    base = dict(edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)
    bad_source = _completed_receipt()
    bad_source["sources"][0]["source_hash"] = None
    with pytest.raises(MCPVideoError):
        attach_receipt_lineage(bad_source, **base)
    malformed_output = _completed_receipt()
    malformed_output["outputs"][0]["output_hash"] = "sha256:deadbeef"  # wrong length
    with pytest.raises(MCPVideoError):
        attach_receipt_lineage(malformed_output, **base)
    no_versions = _completed_receipt()
    no_versions["versions"] = {}
    with pytest.raises(MCPVideoError):
        attach_receipt_lineage(no_versions, **base)


def test_non_completed_receipt_raises():
    receipt = _completed_receipt()
    receipt["status"] = "failed"
    with pytest.raises(MCPVideoError):
        attach_receipt_lineage(receipt, edit_project_id=EDIT_PROJECT_ID, revision_id=REVISION_ID, job_id=JOB_ID)


# --- persisted enriched receipt ----------------------------------------------


def test_persisted_enriched_receipt_is_atomic_and_additive(tmp_path):
    receipt = _completed_receipt()
    target = tmp_path / "receipt.json"
    target.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    before = target.read_text(encoding="utf-8")

    attach_receipt_lineage(
        receipt,
        edit_project_id=EDIT_PROJECT_ID,
        revision_id=REVISION_ID,
        job_id=JOB_ID,
        save_receipt=str(target),
    )

    on_disk = json.loads(target.read_text(encoding="utf-8"))
    assert "lineage" in on_disk
    assert on_disk["lineage"]["edit_project_id"] == EDIT_PROJECT_ID
    assert on_disk["lineage"]["job_id"] == JOB_ID
    # existing receipt content is preserved verbatim
    assert on_disk["steps"] == receipt["steps"]
    assert on_disk["cleanup_manifest"] == receipt["cleanup_manifest"]
    assert on_disk["outputs"] == receipt["outputs"]
    # no stale temp file left beside the receipt
    assert not list(target.parent.glob(".*.tmp"))
    # the lineage rewrite changed exactly one top-level key (lineage)
    prior = json.loads(before)
    prior_keys, disk_keys = set(prior), set(on_disk)
    assert disk_keys - prior_keys == {"lineage"}
    assert prior_keys - disk_keys == set()


# --- detached runner lineage -------------------------------------------------


def _spec(project) -> Path:
    spec = {
        "schema_version": 1,
        "name": "lineage-stage",
        "sources": {"src1": {"path": "in.mp4"}},
        "outputs": {"out1": {"path": "out.mp4"}},
        "steps": [
            {"id": "s1", "op": "probe", "inputs": {"src": "@sources.src1"}},
            {"id": "s2", "op": "convert", "inputs": {"src": "@sources.src1"}, "output": "@outputs.out1"},
        ],
    }
    path = project.root / "spec.json"
    path.write_text(json.dumps(spec))
    return path


def _job(project):
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    return submit_render_job(
        project,
        edit_project_id=ep.edit_project_id,
        revision_id=rev.record_id,
        spec_path=str(_spec(project)),
    )


def test_run_job_attaches_lineage_from_persisted_identity(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project)
    render_jobs.mark_running(project, job.job_id, 424242)
    receipt_path = render_jobs.job_receipt_path(project, job.job_id)
    receipt = _completed_receipt()

    def fake_render(**kwargs):
        # mimic the real engine: persist the canonical receipt, return the success envelope
        save = kwargs.get("save_receipt")
        if save:
            Path(save).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {**receipt, "success": True}

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "succeeded"

    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert "lineage" in persisted
    lineage = persisted["lineage"]
    # lineage identity comes from the persisted job record, not the receipt
    head = get_render_job(project, job.job_id)
    assert lineage["edit_project_id"] == head.edit_project_id == job.edit_project_id
    assert lineage["revision_id"] == head.revision_id == job.revision_id
    assert lineage["job_id"] == head.job_id == job.job_id
    assert lineage["source_digests"] == [SRC_HASH]
    # the render already succeeded; per-step hashes + cleanup manifest are preserved
    assert persisted["steps"] == receipt["steps"]
    assert persisted["cleanup_manifest"] == receipt["cleanup_manifest"]
    assert persisted["status"] == "completed"
    # Lineage attaches to a receipt-only copy (not the envelope) and is atomically
    # persisted before SUCCEEDED/event emission; the async receipt gains exactly
    # ``lineage`` and never the MCP envelope's ``success``.
    assert "success" not in persisted


def test_run_job_persisted_receipt_is_receipt_plus_lineage_not_envelope(tmp_path, monkeypatch):
    """Regression: async persistence adds exactly ``lineage`` — never ``success``.

    The synchronous engine wraps the workflow receipt in a result envelope that
    sets ``success``; the detached runner derives/persists lineage from a
    receipt-only copy, so the persisted async receipt equals the engine receipt
    plus exactly ``lineage`` (never the MCP envelope's ``success``) while every
    original workflow receipt field is preserved unchanged.
    """
    project = open_project(tmp_path / "proj")
    job = _job(project)
    render_jobs.mark_running(project, job.job_id, 424242)
    receipt_path = render_jobs.job_receipt_path(project, job.job_id)
    receipt = _completed_receipt()
    snapshot = copy.deepcopy(receipt)

    def fake_render(**kwargs):
        # mimic the real engine: persist the canonical receipt, return the success envelope
        save = kwargs.get("save_receipt")
        if save:
            Path(save).write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {**receipt, "success": True}

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "succeeded"

    persisted = json.loads(receipt_path.read_text(encoding="utf-8"))
    # lineage is attached ...
    assert "lineage" in persisted
    # ... but the MCP envelope's ``success`` never leaks into the persisted receipt
    assert "success" not in persisted
    # the async receipt is the engine receipt plus exactly ``lineage``: no keys
    # added or removed beyond lineage, and every original field is preserved
    assert set(persisted) == set(snapshot) | {"lineage"}
    assert all(persisted[key] == snapshot[key] for key in snapshot)


def test_run_job_fails_when_lineage_result_not_completed(tmp_path, monkeypatch):
    """A succeeded render whose returned result is not a completed receipt fails closed.

    Lineage is now derived from the authoritative returned receipt, not reread from
    disk, so a result that carries no completed-receipt lineage data (no completed
    status / sources / outputs / versions) fails closed; no success is recorded.
    """
    project = open_project(tmp_path / "proj")
    job = _job(project)
    render_jobs.mark_running(project, job.job_id, 424242)
    minimal = {"success": True, "steps": [{"id": "s1", "status": "completed", "output_hash": OUT_HASH}]}

    def fake_render(**kwargs):
        return dict(minimal)  # returned result carries no completed-receipt lineage data

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "failed"
    head = get_render_job(project, job.job_id)
    assert head.status.value == "failed"
    assert head.error_code == "lineage_failed"


def test_run_job_fails_when_lineage_data_malformed(tmp_path, monkeypatch):
    """A returned result whose lineage cannot be derived fails the detached job; no success is emitted."""
    project = open_project(tmp_path / "proj")
    job = _job(project)
    render_jobs.mark_running(project, job.job_id, 424242)
    bad = _completed_receipt()
    bad["outputs"][0]["output_hash"] = "sha256:deadbeef"  # malformed -> derivation raises

    def fake_render(**kwargs):
        save = kwargs.get("save_receipt")
        if save:
            Path(save).write_text(json.dumps(bad, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return {**bad, "success": True}

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "failed"
    head = get_render_job(project, job.job_id)
    assert head.status.value == "failed"
    assert head.error_code == "lineage_failed"
