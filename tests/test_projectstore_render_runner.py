"""Behavior tests for the detached render runner launch/run contract.

``start_render_job`` is asserted via a monkeypatched ``subprocess.Popen`` (no real
child): argv ``sys.executable -m <module> --project <root> --job-id <id>``,
``shell=False``/``start_new_session=True``/``close_fds=True``, DEVNULL stdio, and
prompt RUNNING+PID recording. ``run_job`` runs in-process against a stubbed engine
to assert the render kwargs (stored safe spec, save/resume receipt, keep_intermediates)
and the succeeded/failed transitions (success, exception, structured error) + pre-start cancel.

kill/reopen IS asserted: the real detached child is killed after stage 1, then
reopened/resumed with unchanged stage-1 hash/count (completed stage skipped).
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

from kinocut.projectstore import (
    append_revision,
    create_edit_project,
    get_render_job,
    open_project,
    start_render_job,
    submit_render_job,
)
from kinocut.projectstore import render_jobs
from kinocut.projectstore import render_runner


def _spec(project):
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
    path = project.root / "spec.json"
    path.write_text(json.dumps(spec))
    return path


def _job(project, *, running=False):
    ep = create_edit_project(project)
    rev = append_revision(project, ep.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    job = submit_render_job(
        project, edit_project_id=ep.edit_project_id, revision_id=rev.record_id, spec_path=str(_spec(project))
    )
    if running:
        render_jobs.mark_running(project, job.job_id, 424242)
    return job


class _FakeProc:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.pid = 424242
        self.blocked = []

    def wait(self, timeout=None):
        self.blocked.append("wait")
        return 0

    def communicate(self, timeout=None):
        self.blocked.append("communicate")
        return (b"", b"")


def test_start_render_job_launch_contract_and_prompt_return(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project)
    launched = {}

    def fake_popen(args, **kwargs):
        proc = _FakeProc(args, **kwargs)
        launched["proc"] = proc
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    rec = start_render_job(project, job.job_id)
    argv = list(launched["proc"].args)
    assert argv[:3] == [sys.executable, "-m", "kinocut.projectstore.render_runner"]
    assert argv[argv.index("--project") + 1] == str(project.root)
    assert argv[argv.index("--job-id") + 1] == job.job_id
    kw = launched["proc"].kwargs
    assert kw["shell"] is False and kw["start_new_session"] is True and kw["close_fds"] is True
    for stream in ("stdin", "stdout", "stderr"):
        assert kw[stream] is subprocess.DEVNULL  # stdio fully detached
    head = get_render_job(project, job.job_id)
    assert head.status.value == "running" and head.runner_pid == 424242  # RUNNING/PID recorded
    assert launched["proc"].blocked == []  # prompt: parent never waited on the child
    assert rec.runner_pid == 424242 and rec.status.value == "running"


def test_run_job_passes_render_contract_and_marks_succeeded(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project, running=True)
    captured = {}
    receipt = {
        "success": True,
        "steps": [
            {"id": "s1", "status": "completed", "output_hash": "sha256:" + "a" * 64},
            {"id": "s2", "status": "completed", "output_hash": "sha256:" + "b" * 64},
        ],
    }

    def fake_render(**kwargs):
        captured.update(kwargs)
        return receipt

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "succeeded"
    assert captured["keep_intermediates"] is True
    assert captured["spec_path"] == str(render_jobs.job_spec_path(project, job.job_id))
    assert captured["save_receipt"] == str(render_jobs.job_receipt_path(project, job.job_id))
    assert captured["resume_receipt"] is None  # no prior receipt to resume from
    head = get_render_job(project, job.job_id)
    assert head.status.value == "succeeded"
    assert head.completed_artifacts == ("sha256:" + "a" * 64, "sha256:" + "b" * 64)
    assert head.stage_index == 2  # progress carried forward from the receipt


def test_run_job_resumes_from_existing_receipt(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project, running=True)
    prior = render_jobs.job_receipt_path(project, job.job_id)
    prior.parent.mkdir(parents=True, exist_ok=True)
    prior.write_text(json.dumps({"prior": True}))
    captured = {}

    def fake_render(**kwargs):
        captured.update(kwargs)
        return {"success": True, "steps": []}

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    render_runner.run_job(project, job.job_id)
    assert captured["resume_receipt"] == str(prior)  # existing receipt handed to the engine


def test_run_job_exception_marks_bounded_failed(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project, running=True)
    exc = RuntimeError("kaboom " + "z" * 500)

    def boom(**_kw):
        raise exc

    monkeypatch.setattr(render_runner, "video_workflow_render", boom)
    assert render_runner.run_job(project, job.job_id) == "failed"
    head = get_render_job(project, job.job_id)
    assert head.status.value == "failed" and head.error_code == "render_failed"
    assert head.error_message == repr(exc)[:256]  # failure text bounded to the cap
    assert len(head.error_message) <= 256


def test_run_job_structured_error_marks_bounded_failed(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project, running=True)

    def fail(**_kw):
        return {"success": False, "error": {"code": "bad_source", "message": "missing file"}}

    monkeypatch.setattr(render_runner, "video_workflow_render", fail)
    assert render_runner.run_job(project, job.job_id) == "failed"
    head = get_render_job(project, job.job_id)
    assert head.status.value == "failed"
    assert head.error_code == "bad_source" and head.error_message == "missing file"


def test_run_job_cooperative_pre_start_cancel_skips_render(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project)
    render_jobs.cancel_render_job(project, job.job_id)  # durable CANCELLED observed before render
    calls = []

    def fake_render(**_kw):
        calls.append(1)
        return {"success": True, "steps": []}

    monkeypatch.setattr(render_runner, "video_workflow_render", fake_render)
    assert render_runner.run_job(project, job.job_id) == "cancelled"
    assert calls == []  # cooperative cancel short-circuits before the engine is invoked
    assert get_render_job(project, job.job_id).status.value == "cancelled"


def test_real_child_kill_reopen_resume_skips_completed_stage(tmp_path, monkeypatch):
    project = open_project(tmp_path / "proj")
    job = _job(project)
    monkeypatch.setenv("KINOCUT_RENDER_RUNNER_FIXTURE", "1")
    monkeypatch.setenv("KINOCUT_RENDER_RUNNER_FIXTURE_WAIT", "20")

    running = start_render_job(project, job.job_id)
    receipt_path = render_jobs.job_receipt_path(project, job.job_id)
    counts_path = receipt_path.parent / "fixture_progress.json"
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if counts_path.exists():
            counts = json.loads(counts_path.read_text())
            if counts.get("s1") == 1:
                break
        time.sleep(0.05)
    else:
        raise AssertionError("runner did not persist stage 1")

    first_receipt = json.loads(receipt_path.read_text())
    first_hash = first_receipt["steps"][0]["output_hash"]
    failed = render_jobs.terminate_render_job(project, job.job_id)
    assert failed.status.value == "failed"
    assert failed.error_code == "terminated"
    assert failed.runner_pid is None

    reopened = open_project(project.root)
    resumed = render_jobs.resume_render_job(reopened, job.job_id)
    assert resumed.status.value == "queued"
    restarted = start_render_job(reopened, job.job_id)
    assert restarted.runner_pid != running.runner_pid

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        head = get_render_job(reopened, job.job_id)
        if head.status.value == "succeeded":
            break
        time.sleep(0.05)
    else:
        render_jobs.terminate_render_job(reopened, job.job_id)
        raise AssertionError("resumed runner did not succeed")

    final_receipt = json.loads(receipt_path.read_text())
    counts = json.loads(counts_path.read_text())
    assert counts == {"s1": 1, "s2": 1}
    assert final_receipt["steps"][0]["output_hash"] == first_hash
    assert final_receipt["success"] is True
