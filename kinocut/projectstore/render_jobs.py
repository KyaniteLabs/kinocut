"""Persistent append-only Phase-1 render-job repository."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import RenderJobRecord, RenderJobStatus, can_transition_job
from kinocut.projectstore.edit_projects import _append_transaction, get_branch
from kinocut.projectstore.events import _build_event_locked
from kinocut.projectstore.store import (
    Project,
    _project_lock,
    _with_record_id,
    _write_atomically,
    append_record_locked,
    read_records,
    safe_target,
)

_SHA256_LEN = len("sha256:" + "0" * 64)
_MESSAGE_CAP = 256


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_job_id(job_id: Any) -> str:
    if not (
        isinstance(job_id, str)
        and job_id.startswith("job:")
        and len(job_id) == 4 + 64
        and all(c in "0123456789abcdef" for c in job_id[4:])
    ):
        raise contract_error("job_id is not a valid identity", INVALID_RECORD)
    return job_id


def _job_subdir(job_id: str) -> PurePosixPath:
    return PurePosixPath(".kinocut", "jobs", job_id[4:])


def _job_dir(project: Project, job_id: str) -> Path:
    return safe_target(project, _job_subdir(job_id))


def job_receipt_path(project: Project, job_id: str) -> Path:
    """Project-absolute path of the wrapped engine's resume receipt for one job."""
    return safe_target(project, _job_subdir(job_id) / "receipt.json")


def job_lease_path(project: Project, job_id: str) -> Path:
    """Project-absolute path of the runner-held identity lease."""
    return safe_target(project, _job_subdir(job_id) / "runner.lock")


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("sha256:") and len(value) == _SHA256_LEN


def _job_heads(project: Project) -> dict[str, RenderJobRecord]:
    """Map each job_id to its single non-superseded head; fail closed on an ambiguous chain."""
    by_job: dict[str, list[RenderJobRecord]] = {}
    for record in read_records(project, "render_job"):
        by_job.setdefault(record.job_id, []).append(record)
    heads: dict[str, RenderJobRecord] = {}
    for job_id, recs in by_job.items():
        superseded = {r.supersedes for r in recs if r.supersedes}
        candidates = [r for r in recs if r.record_id not in superseded]
        if len(candidates) != 1:
            raise contract_error("render job has an ambiguous head", INVALID_RECORD)
        heads[job_id] = candidates[0]
    return heads


def _build_from(project: Project, head: RenderJobRecord, target: RenderJobStatus, **changes: Any) -> RenderJobRecord:
    """Build and validate a frozen successor of ``head`` (lock held by caller, no append);
    returns the record with its canonical ``record_id`` populated so a paired record (the
    success event) can reference it before the append. Progress carries forward unless
    overridden; the failure summary resets and the active stage clears on re-queue."""
    fields: dict[str, Any] = head.model_dump(mode="json")
    fields["record_id"] = None
    fields.update(
        stage=changes.get("stage", None if target is RenderJobStatus.QUEUED else head.stage),
        stage_index=changes.get("stage_index", head.stage_index),
        runner_pid=changes.get("runner_pid", head.runner_pid),
        completed_artifacts=changes.get("completed_artifacts", head.completed_artifacts),
        error_code=changes.get("error_code"),
        error_message=changes.get("error_message"),
        status=target,
        created_at=_now(),
        supersedes=head.record_id,
    )
    record, _ = _with_record_id(validate_record(RenderJobRecord, fields))
    return record


def _append_from(project: Project, head: RenderJobRecord, target: RenderJobStatus, **changes: Any) -> RenderJobRecord:
    """Append a frozen successor of ``head`` (lock held by caller); see :func:`_build_from`."""
    return append_record_locked(project, _build_from(project, head, target, **changes))


def _transition(project: Project, job_id: str, target: RenderJobStatus, **changes: Any) -> RenderJobRecord:
    """Poll-first lifecycle move: read the head under the lock, enforce a legal transition, append."""
    with _project_lock(project):
        head = _job_heads(project).get(job_id)
        if head is None:
            raise contract_error("render job not found", INVALID_RECORD)
        if not can_transition_job(head.status, target):
            raise contract_error(f"illegal render-job transition {head.status.value} -> {target.value}", INVALID_RECORD)
        return _append_from(project, head, target, **changes)


def _resolve_spec(project: Project, spec_path: Any) -> Path:
    """Resolve ``spec_path`` to an absolute in-workspace file, rejecting escapes and host paths."""
    if not isinstance(spec_path, str) or not spec_path:
        raise contract_error("spec_path must be a non-empty string", INVALID_RECORD)
    if "\x00" in spec_path:
        raise contract_error("spec_path contains null bytes", INVALID_RECORD)
    raw = Path(spec_path)
    candidate = raw.resolve() if raw.is_absolute() else (project.root / raw).resolve()
    try:
        candidate.relative_to(project.root.resolve())
    except ValueError:
        raise contract_error("spec_path must live inside the project workspace", INVALID_RECORD) from None
    if not candidate.is_file():
        raise contract_error("workflow spec file not found", INVALID_RECORD)
    return candidate


def _extract_progress(receipt: Any) -> tuple[tuple[str, ...], int]:
    """Ordered, de-duped output digests of completed stages plus the completed-stage count."""
    steps = receipt.get("steps", []) if isinstance(receipt, dict) else []
    artifacts: list[str] = []
    completed = 0
    for step in steps:
        if isinstance(step, dict) and step.get("status") == "completed":
            completed += 1
            if _is_sha256(step.get("output_hash")):
                artifacts.append(step["output_hash"])
    return tuple(dict.fromkeys(artifacts)), completed


def _load_receipt(project: Project, job_id: str, *, strict: bool) -> dict[str, Any] | None:
    """Read the resume receipt. Strict mode returns ``None`` when absent and fails closed on a corrupt/malformed file; best-effort mode returns ``{}`` so a terminal transition completes even with a torn receipt."""
    path = job_receipt_path(project, job_id)
    if not path.exists():
        return None if strict else {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if strict:
            raise contract_error("render job receipt is unreadable or corrupt", INVALID_RECORD) from exc
        return {}
    if not isinstance(data, dict):
        if strict:
            raise contract_error("render job receipt is malformed", INVALID_RECORD)
        return {}
    return data


def _best_effort_progress(project: Project, job_id: str) -> tuple[tuple[str, ...], int]:
    return _extract_progress(_load_receipt(project, job_id, strict=False))


def mark_running(project: Project, job_id: str, pid: int) -> RenderJobRecord:
    return _transition(project, job_id, RenderJobStatus.RUNNING, runner_pid=pid, stage="running")


def mark_succeeded(project: Project, job_id: str, receipt: dict[str, Any]) -> RenderJobRecord:
    """Advance a RUNNING job to SUCCEEDED and append exactly one ``render.completed``
    kernel event, both under one project lock and one exception-atomic append
    transaction over the distinct ``render_job`` and ``kernel_event`` kinds. A repeat
    call fails closed on the illegal SUCCEEDED -> SUCCEEDED transition before any
    append, so the event is never duplicated. The successor and the event are
    validated/built before the transactional append, so a raised second append rolls
    both record logs back to their pre-call bytes (exception-atomic, not
    crash-atomic) and a retry produces exactly one succeeded head and one event."""
    artifacts, completed = _extract_progress(receipt)
    with _project_lock(project):
        head = _job_heads(project).get(job_id)
        if head is None:
            raise contract_error("render job not found", INVALID_RECORD)
        if not can_transition_job(head.status, RenderJobStatus.SUCCEEDED):
            raise contract_error(
                f"illegal render-job transition {head.status.value} -> {RenderJobStatus.SUCCEEDED.value}",
                INVALID_RECORD,
            )
        succeeded = _build_from(
            project,
            head,
            RenderJobStatus.SUCCEEDED,
            stage="completed",
            stage_index=completed,
            completed_artifacts=artifacts,
            runner_pid=None,
        )
        event = _build_event_locked(
            project,
            "render.completed",
            edit_project_id=head.edit_project_id,
            revision_id=head.revision_id,
            job_id=job_id,
            subject_record_id=succeeded.record_id,
        )
        _append_transaction(project, [succeeded, event])
        return succeeded


def mark_failed(project: Project, job_id: str, code: str, message: str) -> RenderJobRecord:
    artifacts, completed = _best_effort_progress(project, job_id)
    return _transition(
        project,
        job_id,
        RenderJobStatus.FAILED,
        stage="failed",
        stage_index=completed,
        completed_artifacts=artifacts,
        error_code=(code or "render_failed")[:64],
        error_message=(message or "")[:_MESSAGE_CAP],
        runner_pid=None,
    )


def submit_render_job(
    project: Project,
    *,
    edit_project_id: str,
    revision_id: str,
    spec_path: str,
    created_by: str = "agent",
) -> RenderJobRecord:
    """Validate project/revision identity and a safe workflow spec, then persist a QUEUED snapshot with a frozen immutable spec copy. No runner is spawned in this slice."""
    from kinocut.workflow import validate_workflow_spec

    with _project_lock(project):
        head = get_branch(project, edit_project_id)
        if head.head_revision_id is None or revision_id != head.head_revision_id:
            raise contract_error("revision_id must match the current main branch head", INVALID_RECORD)
        spec_abs = _resolve_spec(project, spec_path)
        verdict = validate_workflow_spec(str(spec_abs))  # fail closed on an unsafe/invalid spec
        spec_bytes = spec_abs.read_bytes()
        spec_digest = "sha256:" + hashlib.sha256(spec_bytes).hexdigest()
        job_id = "job:" + secrets.token_hex(32)
        job_dir = _job_dir(project, job_id)
        job_dir.mkdir(parents=True, exist_ok=True)
        _write_atomically(job_dir / "spec.json", lambda handle: handle.write(spec_bytes), binary=True)
        fields: dict[str, Any] = {
            "job_id": job_id,
            "edit_project_id": edit_project_id,
            "revision_id": revision_id,
            "status": RenderJobStatus.QUEUED,
            "workflow_spec_digest": spec_digest,
            "spec_path": (_job_subdir(job_id) / "spec.json").as_posix(),
            "stage": "queued",
            "stage_index": 0,
            "stage_total": len(verdict["steps"]),
            "project_id": project.project_id,
            "created_by": created_by,
            "created_at": _now(),
        }
        return append_record_locked(project, validate_record(RenderJobRecord, fields))


def get_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Poll-first read of the current job head."""
    _require_job_id(job_id)
    head = _job_heads(project).get(job_id)
    if head is None:
        raise contract_error("render job not found", INVALID_RECORD)
    return head


def job_spec_path(project: Project, job_id: str) -> Path:
    """Absolute in-store path of the job's frozen immutable workflow spec; a stable integration hook for the detached runner that resolves the stored workspace-relative ``spec_path`` to its symlink-safe absolute location, failing closed when the job carries no frozen spec."""
    head = get_render_job(project, job_id)
    if not head.spec_path:
        raise contract_error("render job has no frozen spec", INVALID_RECORD)
    return safe_target(project, PurePosixPath(head.spec_path))


def render_job_status(project: Project, job_id: str) -> dict[str, Any]:
    """The lifecycle head merged with the wrapped receipt's per-stage progress; a missing receipt is benign, a corrupt one fails closed (privacy-safe)."""
    head = get_render_job(project, job_id)
    receipt = _load_receipt(project, job_id, strict=True) or {}
    completed = [
        step for step in (receipt.get("steps") or []) if isinstance(step, dict) and step.get("status") == "completed"
    ]
    return {
        "job_id": head.job_id,
        "status": head.status.value,
        "stage": head.stage,
        "stage_index": head.stage_index,
        "stage_total": head.stage_total,
        "runner_pid": head.runner_pid,
        "completed_steps": completed,
        "completed_artifacts": list(head.completed_artifacts),
        "error_code": head.error_code,
        "error_message": head.error_message,
        "workflow_spec_digest": head.workflow_spec_digest,
    }


def cancel_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Durable CANCELLED marker (legal transition only); a runner observes it cooperatively."""
    _require_job_id(job_id)
    return _transition(project, job_id, RenderJobStatus.CANCELLED, runner_pid=None)


def resume_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Resume a FAILED/CANCELLED job back to QUEUED (legal transition only); progress carries forward."""
    _require_job_id(job_id)
    return _transition(project, job_id, RenderJobStatus.QUEUED)


def _runner_lease_is_held(project: Project, job_id: str) -> bool:
    lease = job_lease_path(project, job_id)
    lease.parent.mkdir(parents=True, exist_ok=True)
    with lease.open("a+b") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        fcntl.flock(handle, fcntl.LOCK_UN)
        return False


def terminate_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Kill only a live runner proven by its process group and held job lease."""
    _require_job_id(job_id)
    with _project_lock(project):
        head = _job_heads(project).get(job_id)
        if head is None:
            raise contract_error("render job not found", INVALID_RECORD)
        if head.status is not RenderJobStatus.RUNNING:
            return head

        pid = head.runner_pid
        verified = isinstance(pid, int) and pid > 1 and pid != os.getpid() and pid != os.getpgrp()
        if verified:
            try:
                verified = os.getpgid(pid) == pid and _runner_lease_is_held(project, job_id)
            except OSError:
                verified = False

        artifacts, completed = _best_effort_progress(project, job_id)
        error_code = "orphaned_runner"
        error_message = "runner identity could not be verified"
        if verified:
            os.killpg(pid, signal.SIGKILL)
            error_code = "terminated"
            error_message = "runner terminated by request"
        return _append_from(
            project,
            head,
            RenderJobStatus.FAILED,
            stage="failed",
            stage_index=completed,
            completed_artifacts=artifacts,
            error_code=error_code,
            error_message=error_message,
            runner_pid=None,
        )


def start_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Spawn the detached runner for ``job_id``, persist RUNNING with its PID, and return; the child owns its own terminal transition."""
    _require_job_id(job_id)
    proc = subprocess.Popen(  # noqa: S603 - argv is fully controlled; shell is never used
        [
            sys.executable,
            "-m",
            "kinocut.projectstore.render_runner",
            "--project",
            str(project.root),
            "--job-id",
            job_id,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
        shell=False,
    )
    return mark_running(project, job_id, proc.pid)


def reconcile_render_jobs(project: Project, *, is_alive: Callable[[int], bool] | None = None) -> list[RenderJobRecord]:
    """Reconcile RUNNING snapshots against caller-supplied liveness facts: any RUNNING job whose ``runner_pid`` is not reported alive moves to FAILED (recoverable via :func:`resume_render_job`). Idempotent."""
    changed: list[RenderJobRecord] = []
    with _project_lock(project):
        for job_id, head in _job_heads(project).items():
            if head.status is not RenderJobStatus.RUNNING:
                continue
            if is_alive is not None and head.runner_pid is not None and is_alive(head.runner_pid):
                continue
            artifacts, completed = _best_effort_progress(project, job_id)
            changed.append(
                _append_from(
                    project,
                    head,
                    RenderJobStatus.FAILED,
                    stage="failed",
                    stage_index=completed,
                    completed_artifacts=artifacts,
                    error_code="orphaned_runner",
                    error_message="runner is no longer alive",
                    runner_pid=None,
                )
            )
    return changed
