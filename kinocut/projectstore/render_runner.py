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
import os
import sys
import time

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
    # Production ALWAYS invokes the synchronous workflow engine with keep_intermediates=True;
    # the executor writes a valid progressive receipt after every completed stage, so a
    # killed/resumed run reads ONE authoritative resume cursor (no fixture/parallel path).
    try:
        result = video_workflow_render(
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
