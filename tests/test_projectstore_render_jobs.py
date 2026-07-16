"""Behavior tests for the persistent render-job repository (Phase-1, slice 1: storage only).

No subprocess and no runner: lifecycle states are driven through the runner-facing
transition helpers (``mark_running`` / ``mark_succeeded`` / ``mark_failed``) so the
append-only supersession chain, canonical reopen persistence, legal transitions,
caller-supplied orphan reconciliation, and privacy/path rejection are exercised
purely at the storage boundary.
"""

from __future__ import annotations

import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    cancel_render_job,
    create_edit_project,
    get_render_job,
    open_project,
    reconcile_render_jobs,
    render_job_status,
    resume_render_job,
    submit_render_job,
)
from kinocut.projectstore import render_jobs
from kinocut.projectstore.store import read_records


def _rev(project):
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    return ep.edit_project_id, rev.record_id


def _write_spec(project, *, name="spec.json"):
    spec = {
        "schema_version": 1,
        "name": "two-stage",
        "sources": {"src1": {"path": "in.mp4"}},
        "outputs": {"out1": {"path": "out.mp4"}},
        "steps": [
            {"id": "s1", "op": "probe", "inputs": {"src": "@sources.src1"}},
            {"id": "s2", "op": "convert", "inputs": {"src": "@sources.src1"}, "output": "@outputs.out1"},
        ],
    }
    path = project.root / name
    path.write_text(json.dumps(spec))
    return path


def _run(project, job_id, pid=999999):
    return render_jobs.mark_running(project, job_id, pid)


def test_submit_records_queued_snapshot_with_frozen_spec(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    spec_path = _write_spec(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(spec_path))
    assert job.status.value == "queued"
    assert job.stage_total == 2 and job.stage_index == 0
    assert job.workflow_spec_digest.startswith("sha256:")
    assert job.spec_path == f".kinocut/jobs/{job.job_id[4:]}/spec.json"
    assert str(tmp_path) not in json.dumps(job.model_dump(mode="json"))  # privacy: no host path
    # the spec is frozen as an immutable copy addressed by its content digest
    frozen = (project.root / job.spec_path).read_bytes()
    assert "sha256:" + hashlib.sha256(frozen).hexdigest() == job.workflow_spec_digest
    # mutating the original workspace spec does not change the frozen snapshot
    spec_path.write_text(json.dumps({"mutated": True}))
    assert (project.root / job.spec_path).read_bytes() == frozen
    with pytest.raises(MCPVideoError):  # revision identity is enforced
        submit_render_job(project, edit_project_id=ep_id, revision_id="sha256:" + "0" * 64, spec_path=str(spec_path))


def test_legal_and_illegal_lifecycle_transitions(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    assert cancel_render_job(project, job.job_id).status.value == "cancelled"  # QUEUED -> CANCELLED
    assert resume_render_job(project, job.job_id).status.value == "queued"  # CANCELLED -> QUEUED
    with pytest.raises(MCPVideoError):  # QUEUED -> QUEUED illegal
        resume_render_job(project, job.job_id)
    cancel_render_job(project, job.job_id)
    with pytest.raises(MCPVideoError):  # CANCELLED -> CANCELLED illegal
        cancel_render_job(project, job.job_id)
    resume_render_job(project, job.job_id)
    _run(project, job.job_id, 123456)
    render_jobs.mark_succeeded(
        project, job.job_id, {"steps": [{"id": "s1", "status": "completed", "output_hash": "sha256:" + "a" * 64}]}
    )
    assert get_render_job(project, job.job_id).status.value == "succeeded"
    with pytest.raises(MCPVideoError):  # terminal cannot be cancelled
        cancel_render_job(project, job.job_id)
    with pytest.raises(MCPVideoError):  # terminal cannot be resumed
        resume_render_job(project, job.job_id)


def test_canonical_reopen_persists_head(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    _run(project, job.job_id, 4242)
    reopened = open_project(project.root)
    head = get_render_job(reopened, job.job_id)
    assert head.status.value == "running"
    assert head.runner_pid == 4242
    assert head.record_id == get_render_job(project, job.job_id).record_id  # canonical id stable across reopen


def test_stale_snapshot_is_superseded_but_chain_retained(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    queued_id = job.record_id
    running = _run(project, job.job_id, 7)
    cancelled = cancel_render_job(project, job.job_id)
    head = get_render_job(project, job.job_id)
    assert head.record_id == cancelled.record_id  # only the latest head is current
    assert running.supersedes == queued_id  # stale snapshots link forward ...
    assert cancelled.supersedes == running.record_id
    chain = read_records(project, "render_job")  # ... yet the whole chain is retained (append-only)
    assert len(chain) == 3


def test_failed_and_resume_preserve_progress(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    _run(project, job.job_id, 555)
    render_jobs.mark_failed(project, job.job_id, "boom", "runner crashed mid-stage")
    failed = get_render_job(project, job.job_id)
    assert failed.status.value == "failed" and failed.error_code == "boom"
    resumed = resume_render_job(project, job.job_id)
    assert resumed.status.value == "queued"
    assert resumed.completed_artifacts == failed.completed_artifacts  # progress carried forward for resume


def test_orphan_reconcile_uses_caller_supplied_liveness(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    live = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    dead = submit_render_job(
        project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project, name="spec2.json"))
    )
    _run(project, live.job_id, 111)
    _run(project, dead.job_id, 222)
    changed = reconcile_render_jobs(project, is_alive=lambda pid: pid == 111)
    assert {c.job_id for c in changed} == {dead.job_id}
    assert get_render_job(project, dead.job_id).error_code == "orphaned_runner"
    assert get_render_job(project, live.job_id).status.value == "running"  # live runner untouched
    assert reconcile_render_jobs(project, is_alive=lambda pid: pid == 111) == []  # idempotent
    changed2 = reconcile_render_jobs(project)  # fail-closed default: no probe -> all RUNNING orphaned
    assert len(changed2) == 1 and changed2[0].job_id == live.job_id


def test_privacy_and_path_rejection(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    spec_path = _write_spec(project)
    for bad in ("/etc/passwd", str(tmp_path / "outside.json"), "", "  "):
        with pytest.raises(MCPVideoError):
            submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=bad)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(spec_path))
    assert not job.spec_path.startswith("/") and ".." not in job.spec_path  # only a project-relative private path


def test_concurrent_cancel_is_serialized(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    wins, errors = [], []

    def _race():
        try:
            wins.append(cancel_render_job(project, job.job_id).record_id)
        except MCPVideoError:
            errors.append(True)

    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(lambda _: _race(), range(16)))
    assert len(wins) == 1  # exactly one legal QUEUED -> CANCELLED wins the poll-first race
    assert len(errors) == 15
    assert get_render_job(project, job.job_id).status.value == "cancelled"


def test_corrupt_receipt_fails_closed_on_read(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    assert render_job_status(project, job.job_id)["completed_steps"] == []  # no receipt yet is benign
    _run(project, job.job_id, 999)
    render_jobs.job_receipt_path(project, job.job_id).write_text("{not json", encoding="utf-8")
    with pytest.raises(MCPVideoError):  # corrupt resume cursor fails closed (privacy-safe)
        render_job_status(project, job.job_id)


def test_status_merges_head_with_receipt_progress(tmp_path):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    _run(project, job.job_id, 31337)
    render_jobs.job_receipt_path(project, job.job_id).write_text(
        json.dumps(
            {"steps": [{"id": "s1", "status": "completed", "output_hash": "sha256:" + "b" * 64}], "status": "running"}
        )
    )
    s = render_job_status(project, job.job_id)
    assert s["status"] == "running" and s["runner_pid"] == 31337
    assert [step["id"] for step in s["completed_steps"]] == ["s1"]


def test_synchronous_workflow_engine_is_unchanged():
    import kinocut.workflow as wf
    from kinocut.workflow.executor import render_workflow as exec_render
    from kinocut.workflow.validator import validate_workflow_spec as validator_fn
    import kinocut.projectstore.render_jobs  # noqa: F401  — the storage layer wraps, never rebinds

    assert wf.render_workflow is exec_render
    assert wf.validate_workflow_spec is validator_fn


def test_terminate_rejects_self_pid_without_signalling(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    _run(project, job.job_id, os.getpid())
    signals = []
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))

    failed = render_jobs.terminate_render_job(project, job.job_id)

    assert signals == []
    assert failed.status.value == "failed"
    assert failed.error_code == "orphaned_runner"


def test_terminate_rejects_acquirable_lease_without_signalling(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    _run(project, job.job_id, 424242)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    signals = []
    monkeypatch.setattr(os, "killpg", lambda *args: signals.append(args))

    failed = render_jobs.terminate_render_job(project, job.job_id)

    assert signals == []
    assert failed.error_code == "orphaned_runner"


def test_terminate_terminal_job_is_idempotent_and_never_signals(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    ep_id, rev_id = _rev(project)
    job = submit_render_job(project, edit_project_id=ep_id, revision_id=rev_id, spec_path=str(_write_spec(project)))
    cancelled = cancel_render_job(project, job.job_id)
    monkeypatch.setattr(os, "killpg", lambda *_: pytest.fail("terminal job was signalled"))

    assert render_jobs.terminate_render_job(project, job.job_id).record_id == cancelled.record_id
