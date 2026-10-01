"""Detached render-job runner (internal).

``start_render_job`` is the parent API (re-exported from
:mod:`kinocut.projectstore.render_jobs`): it spawns this module
(``python -m kinocut.projectstore.render_runner --project <root> --job-id <id>``)
in a new session with stdio detached, persists RUNNING with the child PID, and
returns promptly. The child (``main``) opens the project, observes a cooperative
cancel, resumes from an existing receipt when one is present, invokes the
synchronous workflow engine with ``keep_intermediates=True``, and records the
terminal (succeeded/failed) via the render-job repository.
Stop requests make the runner leave execution; the stop controller/reconciliation
owns the terminal record after observing group quiescence and lease release.

INTERNAL ONLY: no daemon, no public MCP/CLI surface, no raw host path persisted.
"""

from __future__ import annotations

import argparse
import contextlib
import logging
from typing import Any
from pathlib import Path
import os
import sys
import time

from kinocut.projectstore._filelock import lock_exclusive
from kinocut.errors import MCPVideoError
from kinocut.projectstore.render_jobs import (
    RenderJobStatus,
    get_render_job,
    job_lease_path,
    job_receipt_path,
    job_spec_path,
    mark_failed,
    _runner_stop_observer,
    mark_succeeded,
    start_render_job,
)
from kinocut.projectstore.store import Project, open_project
from kinocut.projectstore.render_control import CANCELLATION_REQUESTED, STOP_REQUEST_STAGES, watch_runner_stop
from kinocut.workflow.executor import attach_receipt_lineage, render_workflow

logger = logging.getLogger(__name__)

__all__ = ["run_job", "start_render_job"]


def run_job(project: Project, job_id: str) -> str:
    """Run one job until completion or a stop request and return its outcome label.

    Observes a cooperative cancel, then invokes the synchronous workflow engine
    with the stored frozen spec, resuming from an existing receipt, and records
    the terminal (succeeded/failed) with bounded failure text.
    A requested cancelled/failed label means this runner leaves execution; its
    stored job remains RUNNING until the stop controller confirms quiescence.
    """
    if get_render_job(project, job_id).status is RenderJobStatus.CANCELLED:
        return "cancelled"
    if requested := _requested_stop_label(project, job_id):
        return requested
    receipt_path = job_receipt_path(project, job_id)
    resume_receipt = str(receipt_path) if receipt_path.exists() else None
    # Production ALWAYS invokes the synchronous workflow engine with keep_intermediates=True;
    # the executor writes a valid progressive receipt after every completed stage, so a
    # killed/resumed run reads ONE authoritative resume cursor (no fixture/parallel path).
    try:
        result = render_workflow(
            spec_path=str(job_spec_path(project, job_id)),
            resume_receipt=resume_receipt,
            save_receipt=str(receipt_path),
            keep_intermediates=True,
        )
    except Exception as exc:  # defensive: never lose a terminal
        if requested := _requested_stop_label(project, job_id):
            return requested
        logger.warning("Detached workflow render failed", exc_info=True)
        if isinstance(exc, MCPVideoError):
            error = exc.to_dict()
            mark_failed(project, job_id, error["code"], error["message"])
        else:
            mark_failed(project, job_id, "internal_error", "An internal error occurred. Check server logs for details.")
        return "failed"
    if requested := _requested_stop_label(project, job_id):
        return requested
    if isinstance(result, dict):
        try:
            # The engine returns the authoritative receipt without transport metadata;
            # derive/persist lineage directly from it — never reread the file.
            result = _attach_job_lineage(project, job_id, receipt_path, result)
        except Exception:  # lineage is required provenance: never succeed without it
            logger.warning("Detached workflow lineage attachment failed", exc_info=True)
            if requested := _requested_stop_label(project, job_id):
                return requested
            mark_failed(project, job_id, "lineage_failed", "workflow receipt lineage could not be attached")
            return "failed"
        try:
            mark_succeeded(project, job_id, result)
        except MCPVideoError:
            if requested := _requested_stop_label(project, job_id):
                return requested
            raise
        return "succeeded"
    mark_failed(project, job_id, "render_failed", "Workflow engine returned no receipt")
    return "failed"


def _requested_stop_label(project: Project, job_id: str) -> str | None:
    head = get_render_job(project, job_id)
    if head.status is RenderJobStatus.RUNNING and head.stage in STOP_REQUEST_STAGES:
        return "cancelled" if head.stage == CANCELLATION_REQUESTED else "failed"
    return None


def _attach_job_lineage(project: Project, job_id: str, receipt_path: Path, receipt: dict[str, Any]) -> dict[str, Any]:
    """Fail-closed: attach a validated ``ReceiptLineage`` to the returned receipt.

    Derives lineage from the authoritative receipt the synchronous engine already
    returned (carrying its recorded source/output hashes and ``versions``) and the
    persisted job identity, then atomically rewrites the canonical receipt path —
    strictly additive (per-step hashes and the cleanup manifest are preserved) and
    confined to the project workspace. Lineage is REQUIRED provenance for a
    detached render job: any derive/write failure propagates to the caller so the
    job is failed rather than recorded as succeeded without valid lineage. Returns
    the enriched receipt.

    The workflow engine returns receipt data directly; MCP transport envelopes
    never enter this worker. A copy preserves the caller-owned receipt while
    lineage is added and persisted.
    """
    head = get_render_job(project, job_id)
    return attach_receipt_lineage(
        dict(receipt),
        edit_project_id=head.edit_project_id,
        revision_id=head.revision_id,
        job_id=head.job_id,
        save_receipt=str(receipt_path),
        workspace_root=project.root,
    )


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
        lock_exclusive(lease_handle)
        try:
            _await_running_identity(project, args.job_id)
            from kinocut.process_guardian_owner import bind_worker_lease

            with (
                bind_worker_lease(lease_handle.fileno()),
                watch_runner_stop(_runner_stop_observer(project, args.job_id, os.getpid())),
            ):
                run_job(project, args.job_id)
        except Exception as exc:  # defensive: record a bounded failure, never hang the job
            with contextlib.suppress(Exception):
                if _requested_stop_label(project, args.job_id) is None:
                    mark_failed(project, args.job_id, "render_failed", repr(exc)[:256])
    return 0


if __name__ == "__main__":  # pragma: no cover - subprocess entry
    raise SystemExit(main(sys.argv[1:]))
