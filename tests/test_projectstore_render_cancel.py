"""Cancellation is a request until verified renderer execution is quiescent."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import pytest

from kinocut.errors import MCPVideoError
from kinocut.projectstore import (
    append_revision,
    create_edit_project,
    open_project,
    read_records,
    submit_render_job,
)
from kinocut.projectstore import render_jobs, render_runner
from kinocut.projectstore._filelock import lock_exclusive, unlock
from kinocut.projectstore.render_control import CANCELLATION_REQUESTED, group_quiescent


def _job(tmp_path):
    project = open_project(tmp_path / "project")
    edit = create_edit_project(project)
    revision = append_revision(project, edit.edit_project_id, operation_ids=("sha256:" + "1" * 64,))
    spec = project.root / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "name": "cancellation",
                "sources": {"src": {"path": "input.mp4"}},
                "outputs": {},
                "steps": [{"id": "probe", "op": "probe", "inputs": {"src": "@sources.src"}}],
            }
        )
    )
    job = submit_render_job(
        project, edit_project_id=edit.edit_project_id, revision_id=revision.record_id, spec_path=str(spec)
    )
    return project, job


_GROUP_SCRIPT = """
import sys, time, subprocess
from pathlib import Path
from kinocut.projectstore._filelock import lock_exclusive
lease = Path(sys.argv[1]).open('a+b')
if sys.argv[4] == 'lease':
    lock_exclusive(lease)
child_code = '''import sys,time
from pathlib import Path
path = Path(sys.argv[1])
while True:
    with path.open('ab') as handle: handle.write(b'x')
    time.sleep(0.01)
'''
child = subprocess.Popen([sys.executable, '-c', child_code, sys.argv[2]], stdin=subprocess.DEVNULL)
Path(sys.argv[3]).write_text(str(child.pid))
while True: time.sleep(1)
"""


@contextmanager
def _live_group(project, job, tmp_path, *, held_lease):
    if not hasattr(os, "killpg") or not Path("/proc/self/stat").is_file():
        pytest.skip("live group quiescence proof uses Linux process states")
    heartbeat, ready = tmp_path / "heartbeat", tmp_path / "ready"
    proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _GROUP_SCRIPT,
            str(render_jobs.job_lease_path(project, job.job_id)),
            str(heartbeat),
            str(ready),
            "lease" if held_lease else "no-lease",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        start_new_session=True,
        close_fds=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not ready.exists() or not heartbeat.exists():
            assert proc.poll() is None, f"runner exited with {proc.returncode}"
            assert time.monotonic() < deadline
            time.sleep(0.01)
        render_jobs.mark_running(project, job.job_id, proc.pid)
        yield proc, heartbeat
    finally:
        if not group_quiescent(proc.pid):
            os.killpg(proc.pid, signal.SIGKILL)  # only this test's freshly owned group
        proc.wait(timeout=5)
        proc.stderr.close()


def test_cancel_stops_verified_descendants_before_reporting_cancelled(tmp_path):
    project, job = _job(tmp_path)
    with _live_group(project, job, tmp_path, held_lease=True) as (proc, heartbeat):
        cancelled = render_jobs.cancel_render_job(project, job.job_id)
        assert cancelled.status.value == "cancelled" and cancelled.runner_pid is None
        assert group_quiescent(proc.pid)
        before = heartbeat.read_bytes()
        time.sleep(0.05)
        assert heartbeat.read_bytes() == before
        assert render_jobs.get_render_job(open_project(project.root), job.job_id) == cancelled


def test_unverified_live_runner_retains_pid_and_cannot_be_requeued(tmp_path):
    project, job = _job(tmp_path)
    with _live_group(project, job, tmp_path, held_lease=False) as (proc, heartbeat):
        assert render_jobs.reconcile_render_jobs(project) == []
        assert render_jobs.reconcile_render_jobs(project, is_alive=lambda _pid: False) == []
        requested = render_jobs.cancel_render_job(project, job.job_id)
        assert requested.status.value == "running" and requested.runner_pid == proc.pid
        assert requested.stage == CANCELLATION_REQUESTED
        assert requested.error_code == "runner_stop_identity_unverified"
        assert proc.poll() is None
        before = heartbeat.stat().st_size
        time.sleep(0.05)
        assert heartbeat.stat().st_size > before
        with pytest.raises(MCPVideoError):
            render_jobs.resume_render_job(project, job.job_id)
        assert render_jobs.reconcile_render_jobs(project, is_alive=lambda _pid: False) == []
        assert render_jobs.terminate_render_job(project, job.job_id).runner_pid == proc.pid
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
        changed = render_jobs.reconcile_render_jobs(project)
        assert len(changed) == 1 and changed[0].status.value == "cancelled"
        assert changed[0].runner_pid is None


def test_stop_timeout_preserves_identity_and_retry_completes(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    render_jobs.mark_running(project, job.job_id, 424242)
    monkeypatch.setattr(render_jobs, "stop_runner_group", lambda *_: "timeout")
    requested = render_jobs.cancel_render_job(project, job.job_id)
    assert requested.runner_pid == 424242 and requested.status.value == "running"
    assert requested.error_code == "runner_stop_timeout"
    monkeypatch.setattr(render_jobs, "stop_runner_group", lambda *_: "stopped")
    completed = render_jobs.terminate_render_job(project, job.job_id)
    assert completed.status.value == "cancelled" and completed.runner_pid is None


def test_stop_verification_runs_without_project_lock(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    render_jobs.mark_running(project, job.job_id, os.getpid())

    def stop(*_args):
        with (project.root / ".kinocut/locks/project.lock").open("a+b") as handle:
            lock_exclusive(handle, blocking=False)
            unlock(handle)
        return "identity_unverified"

    monkeypatch.setattr(render_jobs, "stop_runner_group", stop)
    assert render_jobs.cancel_render_job(project, job.job_id).runner_pid == os.getpid()


def test_pending_cancel_blocks_success_and_racing_failure_and_runner_start(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    render_jobs.mark_running(project, job.job_id, os.getpid())
    requested = render_jobs.cancel_render_job(project, job.job_id)
    with pytest.raises(MCPVideoError, match="stop is requested"):
        render_jobs.mark_succeeded(project, job.job_id, {})
    assert render_jobs.mark_failed(project, job.job_id, "race", "racing failure") == requested
    monkeypatch.setattr(render_runner, "video_workflow_render", lambda **_kw: pytest.fail("render started"))
    assert render_runner.run_job(project, job.job_id) == "cancelled"
    assert render_jobs.get_render_job(project, job.job_id) == requested
    assert not any(r.event_kind == "render.completed" for r in read_records(project, "kernel_event"))


def test_cancel_during_engine_completion_cannot_emit_success_event(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    render_jobs.mark_running(project, job.job_id, os.getpid())

    def render(**_kwargs):
        render_jobs.cancel_render_job(project, job.job_id)
        return {"success": True, "steps": []}

    monkeypatch.setattr(render_runner, "video_workflow_render", render)
    assert render_runner.run_job(project, job.job_id) == "cancelled"
    assert render_jobs.get_render_job(project, job.job_id).runner_pid == os.getpid()
    assert not any(r.event_kind == "render.completed" for r in read_records(project, "kernel_event"))


def test_start_and_cancel_race_retains_spawned_pid(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    spawning, release, cancel_started = threading.Event(), threading.Event(), threading.Event()

    class FakeProc:
        pid = os.getpid()

    def spawn(*_args, **_kwargs):
        spawning.set()
        assert release.wait(timeout=5)
        return FakeProc()

    def cancel():
        cancel_started.set()
        return render_jobs.cancel_render_job(project, job.job_id)

    monkeypatch.setattr(render_jobs.subprocess, "Popen", spawn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        started = pool.submit(render_jobs.start_render_job, project, job.job_id)
        assert spawning.wait(timeout=5)
        cancelled = pool.submit(cancel)
        assert cancel_started.wait(timeout=5)
        release.set()
        assert started.result(timeout=5).runner_pid == os.getpid()
        requested = cancelled.result(timeout=5)
    assert requested.status.value == "running" and requested.runner_pid == os.getpid()
    assert requested.stage == CANCELLATION_REQUESTED


def test_queued_cancel_prevents_later_spawn(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    assert render_jobs.cancel_render_job(project, job.job_id).status.value == "cancelled"
    monkeypatch.setattr(render_jobs.subprocess, "Popen", lambda *_a, **_k: pytest.fail("spawned cancelled job"))
    with pytest.raises(MCPVideoError):
        render_jobs.start_render_job(project, job.job_id)


def test_start_persistence_failure_reaps_its_new_child(tmp_path, monkeypatch):
    project, job = _job(tmp_path)
    original_popen, original_append = subprocess.Popen, render_jobs.append_record_locked
    spawned = []

    def spawn(*_args, **_kwargs):
        proc = original_popen([sys.executable, "-c", "import time; time.sleep(60)"], start_new_session=True)
        spawned.append(proc)
        return proc

    def fail_running(project, record):
        if record.record_kind == "render_job" and record.status.value == "running":
            raise MCPVideoError("injected running persistence failure", error_type="processing_error")
        return original_append(project, record)

    monkeypatch.setattr(render_jobs.subprocess, "Popen", spawn)
    monkeypatch.setattr(render_jobs, "append_record_locked", fail_running)
    with pytest.raises(MCPVideoError, match="persistence failure"):
        render_jobs.start_render_job(project, job.job_id)
    assert spawned[0].poll() is not None
    assert render_jobs.get_render_job(project, job.job_id).status.value == "queued"
