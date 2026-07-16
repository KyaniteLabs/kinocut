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

import hashlib
import os
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


# --- Deterministic fake ffprobe/ffmpeg for the real-engine kill/reopen test ----------
#
# The recovery test runs the SHIPPED ``video_workflow_render`` against real subprocesses;
# these tiny Python shims stand in for ffprobe/ffmpeg on PATH so stage 1 (probe) completes,
# stage 2 (convert) blocks until SIGKILL, then completes on resume. No fake renderer.

_FAKE_FFPROBE = """\
#!/usr/bin/env python3
import sys
sys.stdout.write(
    '{"streams":[{"codec_type":"video","codec_name":"h264","width":320,"height":240,'
    '"r_frame_rate":"30/1","duration":"2.000000","side_data_list":[]}],'
    '"format":{"duration":"2.000000","bit_rate":"100000","size":"1234",'
    '"format_name":"mov,mp4,m4a,3gp,3g2,mj2"}}'
)
"""

_FAKE_FFMPEG = """\
#!/usr/bin/env python3
import os
import sys
import time

token = os.environ.get("KINOCUT_TEST_FFMPEG_BLOCK_TOKEN", "")
if token and os.path.exists(token):
    while True:
        time.sleep(0.2)

out = sys.argv[-1] if len(sys.argv) > 1 else ""
if out and out != "-":
    parent = os.path.dirname(out)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(out, "wb") as handle:
        handle.write(b"kinocut-fake-ffmpeg-output")
sys.exit(0)
"""


def _install_fake_binaries(bin_dir):
    """Write executable fake ``ffprobe``/``ffmpeg`` into ``bin_dir``; return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    (bin_dir / "ffprobe").write_text(_FAKE_FFPROBE)
    (bin_dir / "ffmpeg").write_text(_FAKE_FFMPEG)
    for name in ("ffprobe", "ffmpeg"):
        os.chmod(bin_dir / name, 0o700)
    return bin_dir


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
    """kill/reopen/resume against the SHIPPED engine + its authoritative resume cursor.

    A real detached child runs the actual ``video_workflow_render`` (no fake
    renderer, no fixture env). Deterministic fake ``ffprobe``/``ffmpeg`` on PATH make
    stage 1 (probe) complete — so the executor persists its genuine progressive
    workflow receipt — and stage 2 (convert) BLOCK inside the fake ``ffmpeg``; the
    runner's whole process group is SIGKILLed; the project is reopened/resumed;
    stage 1 is SKIPPED (reused from the real receipt, never re-executed — proven by
    its carried-over started/ended timestamps, ``skipped: true`` and identical input
    hash) and stage 2 then succeeds. Bounded on Darwin/Linux.
    """
    project = open_project(tmp_path / "proj")
    job = _job(project)
    # The engine resolves declared source paths relative to the frozen spec's directory
    # (the workspace root inside the job store), so the input media must live there.
    job_dir = render_jobs.job_spec_path(project, job.job_id).parent
    (job_dir / "in.mp4").write_bytes(b"kinocut-deterministic-input-media")

    block_token = tmp_path / "block-ffmpeg"
    block_token.write_text("1")  # present -> fake ffmpeg blocks; removed -> it completes
    bin_dir = _install_fake_binaries(tmp_path / "fakebin")
    # The detached child inherits this PATH, so shutil.which finds the fakes in-process.
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    monkeypatch.setenv("KINOCUT_TEST_FFMPEG_BLOCK_TOKEN", str(block_token))

    running = start_render_job(project, job.job_id)
    receipt_path = render_jobs.job_receipt_path(project, job.job_id)

    # Stage 1 (probe) completes -> the executor writes its real progressive receipt.
    deadline = time.monotonic() + 15
    first_receipt = None
    while time.monotonic() < deadline:
        if receipt_path.exists():
            try:
                first_receipt = json.loads(receipt_path.read_text())
            except (OSError, json.JSONDecodeError):
                first_receipt = None
            if first_receipt and first_receipt.get("resume_cursor", {}).get("last_completed_step") == "s1":
                break
        time.sleep(0.05)
    else:
        render_jobs.terminate_render_job(project, job.job_id)
        raise AssertionError("runner did not persist stage 1's real workflow receipt")
    assert first_receipt is not None

    # Stage 1's genuine per-step record — the skip / no-re-execution proof.
    first_s1 = first_receipt["steps"][0]
    assert first_s1["status"] == "completed"
    assert first_receipt["status"] == "in_progress"  # terminal receipt not yet written
    first_input_hash = first_s1["input_hashes"]["src"]
    first_started, first_ended = first_s1["started_at"], first_s1["ended_at"]

    failed = render_jobs.terminate_render_job(project, job.job_id)  # SIGKILL the process group
    assert failed.status.value == "failed"
    assert failed.error_code == "terminated"
    assert failed.runner_pid is None

    block_token.unlink()  # the fake ffmpeg now lets the convert complete on resume

    reopened = open_project(project.root)
    resumed = render_jobs.resume_render_job(reopened, job.job_id)
    assert resumed.status.value == "queued"
    restarted = start_render_job(reopened, job.job_id)
    assert restarted.runner_pid != running.runner_pid

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if get_render_job(reopened, job.job_id).status.value == "succeeded":
            break
        time.sleep(0.05)
    else:
        render_jobs.terminate_render_job(reopened, job.job_id)
        raise AssertionError("resumed runner did not succeed")

    final_receipt = json.loads(receipt_path.read_text())
    final_s1 = final_receipt["steps"][0]
    # stage 1 was SKIPPED on resume: reused from the real receipt, never re-executed.
    assert final_s1["status"] == "completed"
    assert final_s1.get("skipped") is True
    assert final_s1["input_hashes"]["src"] == first_input_hash  # identical input hash
    assert final_s1["started_at"] == first_started  # timestamps carried forward = not re-run
    assert final_s1["ended_at"] == first_ended
    # stage 2 ran to completion on resume.
    assert final_receipt["steps"][1]["status"] == "completed"
    assert final_receipt["steps"][1].get("skipped") is not True
    assert final_receipt["status"] == "completed"
    assert final_receipt["resume_cursor"] == {"last_completed_step": "s2", "next_step": None}
    assert final_receipt["feature_flags"]["resume_used"] is True
    assert final_receipt["feature_flags"]["resumed_from"] == "s2"
    assert (job_dir / "out.mp4").is_file()  # the real convert product landed on disk
    # Regression lock: the terminal receipt's declared output hash must reflect
    # the file that actually landed on disk, NOT a null that the progressive
    # (in_progress) snapshot memoized for the still-absent output before the
    # convert stage produced it. ``_hash_if_exists`` caches None on absence, so
    # progressive output hashing must be isolated from the shared hash_cache.
    out_entry = final_receipt["outputs"][0]
    assert out_entry["id"] == "out1"
    out_hash = out_entry["output_hash"]
    assert out_hash is not None, "terminal output hash poisoned by progressive null cache"
    expected_hash = "sha256:" + hashlib.sha256((job_dir / "out.mp4").read_bytes()).hexdigest()
    assert out_hash == expected_hash
