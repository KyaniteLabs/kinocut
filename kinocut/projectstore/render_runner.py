"""Detached render-job runner (internal).

``start_render_job`` is the parent API (re-exported from
:mod:`kinocut.projectstore.render_jobs`): it spawns this module
(``python -m kinocut.projectstore.render_runner --project <root> --job-id <id>``)
in a new session with stdio detached, persists RUNNING with the child PID, and
returns promptly. The child (``main``) opens the project, observes a cooperative
cancel, resumes from an existing receipt when one is present, invokes the
synchronous workflow engine with ``keep_intermediates=True``, and records the
terminal (succeeded/failed) via the render-job repository.

INTERNAL ONLY: no daemon, no public MCP/CLI surface, no raw host path persisted.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from kinocut.projectstore.render_jobs import (
    RenderJobStatus,
    get_render_job,
    job_lease_path,
    job_receipt_path,
    job_spec_path,
    mark_failed,
    mark_succeeded,
    start_render_job,
)
from kinocut.projectstore.store import Project, open_project
from kinocut.server_tools_workflow import video_workflow_render

__all__ = ["run_job", "start_render_job"]


# Deterministic REAL-subprocess fixture mode (TEST-ONLY).
#
# Gated entirely by the ``KINOCUT_RENDER_RUNNER_FIXTURE`` environment variable, which is never
# set in production: when absent, ``run_job`` always invokes the synchronous workflow engine
# (``video_workflow_render``) with ``keep_intermediates=True``. When set, the real detached
# child instead runs a deterministic two-stage fixture that writes a genuine resume receipt to
# disk, records per-stage execution counts, and blocks after stage 1 — so a parent can SIGKILL
# the actual child and prove kill/reopen/reconcile/resume/restart end to end (no faking).
_FIXTURE_ENV = "KINOCUT_RENDER_RUNNER_FIXTURE"
_FIXTURE_WAIT_ENV = "KINOCUT_RENDER_RUNNER_FIXTURE_WAIT"
_FIXTURE_PROGRESS = "fixture_progress.json"


def _fixture_counts_path(receipt_path: Path) -> Path:
    return receipt_path.parent / _FIXTURE_PROGRESS


def _read_fixture_counts(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, int)}


def _await_termination() -> None:
    """Block (bounded) so the parent can SIGKILL this real child after stage 1.

    The wait budget is bounded so a bug in the kill path self-terminates the child as FAILED
    rather than lingering; under normal operation the parent kills within milliseconds.
    """
    deadline = time.monotonic() + float(os.environ.get(_FIXTURE_WAIT_ENV, "60"))
    while time.monotonic() < deadline:
        time.sleep(0.05)
    raise RuntimeError("fixture was not terminated within the wait budget")


def _fixture_render(*, spec_path: str, resume_receipt: str | None, save_receipt: str, keep_intermediates: bool) -> dict:
    """Deterministic two-stage receipt writer (test-only; mirrors the engine resume contract).

    Completed stages recorded on ``resume_receipt`` are reused (skipped); each executed stage
    writes a progressive partial receipt (``success=False``), bumps its per-stage execution
    count, and — for the first stage of a multi-stage spec — blocks to be SIGKILLed. Once every
    stage is done a ``success=True`` receipt is written. Output hashes are stable (derived from
    the stage id) so resume is provably skip-not-rerun.
    """
    del keep_intermediates  # signature parity only; the fixture keeps no real media
    spec_text = Path(spec_path).read_text(encoding="utf-8")
    spec_hash = "sha256:" + hashlib.sha256(spec_text.encode("utf-8")).hexdigest()
    try:
        steps = json.loads(spec_text).get("steps") or []
    except json.JSONDecodeError:
        steps = []

    receipt_path = Path(save_receipt)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    count_path = _fixture_counts_path(receipt_path)

    done: dict[str, dict] = {}
    if resume_receipt and Path(resume_receipt).exists():
        try:
            prior = json.loads(Path(resume_receipt).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            prior = {}
        for step in (prior.get("steps") or []) if isinstance(prior, dict) else []:
            if isinstance(step, dict) and step.get("status") == "completed":
                done[step.get("id")] = step

    counts = _read_fixture_counts(count_path)
    out_steps: list[dict] = []
    for index, step in enumerate(steps):
        sid = step.get("id") if isinstance(step, dict) else None
        if sid in done:
            out_steps.append(done[sid])  # reused (skipped) — never re-executed
            continue
        entry = {
            "id": sid,
            "status": "completed",
            "output_hash": "sha256:" + hashlib.sha256(str(sid).encode("utf-8")).hexdigest(),
        }
        out_steps.append(entry)
        # Partial receipt first, then the count signal: a parent observing the count is
        # guaranteed the receipt already carries this completed stage.
        receipt_path.write_text(
            json.dumps({"success": False, "spec_hash": spec_hash, "steps": list(out_steps)}),
            encoding="utf-8",
        )
        counts[sid] = counts.get(sid, 0) + 1
        count_path.write_text(json.dumps(counts), encoding="utf-8")
        if index == 0 and len(steps) > 1:
            _await_termination()  # block until the parent SIGKILLs this real child
    receipt_path.write_text(json.dumps({"success": True, "spec_hash": spec_hash, "steps": out_steps}), encoding="utf-8")
    return {"success": True, "spec_hash": spec_hash, "steps": out_steps}


def run_job(project: Project, job_id: str) -> str:
    """Run one job to a terminal in-process and return its terminal label.

    Observes a cooperative cancel, then invokes the synchronous workflow engine
    with the stored frozen spec, resuming from an existing receipt, and records
    the terminal (succeeded/failed) with bounded failure text.
    """
    if get_render_job(project, job_id).status is RenderJobStatus.CANCELLED:
        return "cancelled"
    receipt_path = job_receipt_path(project, job_id)
    resume_receipt = str(receipt_path) if receipt_path.exists() else None
    # Production always invokes the synchronous engine with keep_intermediates=True; the
    # deterministic fixture is engaged solely by the test-only env var (never set in prod).
    render = _fixture_render if os.environ.get(_FIXTURE_ENV) else video_workflow_render
    try:
        result = render(
            spec_path=str(job_spec_path(project, job_id)),
            resume_receipt=resume_receipt,
            save_receipt=str(receipt_path),
            keep_intermediates=True,
        )
    except Exception as exc:  # defensive: never lose a terminal
        mark_failed(project, job_id, "render_failed", repr(exc)[:256])
        return "failed"
    if isinstance(result, dict) and result.get("success"):
        mark_succeeded(project, job_id, result)
        return "succeeded"
    error = result.get("error") if isinstance(result, dict) else None
    mark_failed(
        project,
        job_id,
        (error or {}).get("code") or "render_failed",
        (error or {}).get("message") or "",
    )
    return "failed"


def _await_running_identity(project: Project, job_id: str) -> None:
    """Block (bounded) until the persisted RUNNING record names this process as its runner.

    Closes the child-before-parent-mark-running race: the lease-owning child may render only
    after its own RUNNING record carries this PID, so it never renders on behalf of a stale or
    mismatched runner.
    """
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        job = get_render_job(project, job_id)
        if job.status is RenderJobStatus.RUNNING and job.runner_pid == os.getpid():
            return
        time.sleep(0.01)
    raise RuntimeError("render job did not reach RUNNING with this runner's PID")


def main(argv: list[str]) -> int:
    """Subprocess entry: ``--project <root> --job-id <id>``."""
    parser = argparse.ArgumentParser(prog="kinocut.projectstore.render_runner")
    parser.add_argument("--project", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args(argv)
    project = open_project(args.project)
    lease = job_lease_path(project, args.job_id)
    lease.parent.mkdir(parents=True, exist_ok=True)
    with lease.open("a+b") as lease_handle:
        fcntl.flock(lease_handle, fcntl.LOCK_EX)
        try:
            _await_running_identity(project, args.job_id)
            run_job(project, args.job_id)
        except Exception as exc:  # defensive: record a bounded failure, never hang the job
            with contextlib.suppress(Exception):
                mark_failed(project, args.job_id, "render_failed", repr(exc)[:256])
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry
    raise SystemExit(main(sys.argv[1:]))
