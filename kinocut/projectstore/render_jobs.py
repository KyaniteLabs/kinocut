"""Persistent append-only Phase-1 render-job repository."""

from __future__ import annotations

import hashlib
import contextlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from kinocut.defaults import DEFAULT_RENDER_STOP_TIMEOUT

from kinocut.projectstore._filelock import lock_exclusive, unlock
from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import RenderJobRecord, RenderJobStatus, can_transition_job
from kinocut.projectstore.edit_projects import _append_transaction, get_branch
from kinocut.projectstore.events import _build_event_locked
from kinocut.projectstore import layout
from kinocut.projectstore.render_control import (
    CANCELLATION_REQUESTED,
    STOP_REQUEST_STAGES,
    TERMINATION_REQUESTED,
    group_quiescent,
    stop_runner_group,
)
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
        if (
            head.status is RenderJobStatus.RUNNING
            and target is RenderJobStatus.FAILED
            and head.stage in STOP_REQUEST_STAGES
        ):
            # The stop controller owns the terminal once requested. A racing
            # runner failure must not discard its PID before quiescence.
            return head
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
        if head.stage in STOP_REQUEST_STAGES:
            raise contract_error("render job cannot succeed while stop is requested", INVALID_RECORD)
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
    """Cancel queued work immediately; running work is terminal only after verified
    stop. An unconfirmed stop returns RUNNING with stage cancellation_requested
    and runner_pid retained, allowing retry or later reconciliation."""
    _require_job_id(job_id)
    with _project_lock(project):
        head = _job_heads(project).get(job_id)
        if head is None or not can_transition_job(head.status, RenderJobStatus.CANCELLED):
            raise contract_error("render job cannot be cancelled in its current state", INVALID_RECORD)
        if head.status is RenderJobStatus.QUEUED:
            return _append_from(project, head, RenderJobStatus.CANCELLED, stage="cancelled", runner_pid=None)
        head = _prepare_stop_locked(project, head, CANCELLATION_REQUESTED)
    return _request_stop(project, head)


def resume_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Resume a FAILED/CANCELLED job back to QUEUED (legal transition only); progress carries forward."""
    _require_job_id(job_id)
    return _transition(project, job_id, RenderJobStatus.QUEUED)


def _runner_lease_is_held(project: Project, job_id: str) -> bool:
    lease = job_lease_path(project, job_id)
    lease.parent.mkdir(parents=True, exist_ok=True)
    with lease.open("a+b") as handle:
        try:
            lock_exclusive(handle, blocking=False)
        except BlockingIOError:
            return True
        unlock(handle)
        return False


def _runner_stop_observer(project: Project, job_id: str, owner_pid: int) -> Callable[[], bool]:
    """Cache the validated head until its journal identity or timestamps change.

    Stable rendering polls one stat rather than reparsing the entire job history.
    Stop authority comes only from the normal validated record reader, never a
    private signal file or an unvalidated tail. Forked copies remain inert.
    """
    path = safe_target(project, layout.records_relative_path("render_job"))
    signature: tuple[int, int, int, int] | None = None
    requested = False

    def observe() -> bool:
        nonlocal signature, requested
        if os.getpid() != owner_pid:
            return False
        current = path.stat()
        fingerprint = (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns)
        if fingerprint != signature:
            head = get_render_job(project, job_id)
            requested = (
                head.status is RenderJobStatus.RUNNING
                and head.runner_pid == owner_pid
                and head.stage in STOP_REQUEST_STAGES
            )
            signature = fingerprint
        return requested

    return observe


def terminate_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Request a worker self-stop and wait for group/lease quiescence. Keep
    RUNNING and its PID if stop cannot be confirmed; preserve a prior cancellation
    request so verified completion records CANCELLED rather than FAILED."""
    _require_job_id(job_id)
    with _project_lock(project):
        head = _job_heads(project).get(job_id)
        if head is None:
            raise contract_error("render job not found", INVALID_RECORD)
        if head.status is not RenderJobStatus.RUNNING:
            return head

        head = _prepare_stop_locked(project, head, TERMINATION_REQUESTED)
    return _request_stop(project, head)


def _prepare_stop_locked(project: Project, head: RenderJobRecord, stage: str) -> RenderJobRecord:
    """Append intent while locked; process signaling/waiting happens after release."""
    if head.stage == CANCELLATION_REQUESTED:
        stage = CANCELLATION_REQUESTED
    if head.stage != stage:
        head = _append_from(project, head, RenderJobStatus.RUNNING, stage=stage)
    return head


def _request_stop(project: Project, head: RenderJobRecord) -> RenderJobRecord:
    """Wait without the project lock or external PID signals; retain unconfirmed work."""
    outcome = stop_runner_group(head.runner_pid, lambda: _runner_lease_is_held(project, head.job_id))
    with _project_lock(project):
        current = _job_heads(project).get(head.job_id)
        if current is None:
            raise contract_error("render job not found", INVALID_RECORD)
        if current.status is not RenderJobStatus.RUNNING:
            return current
        if current.runner_pid != head.runner_pid or current.stage not in STOP_REQUEST_STAGES:
            raise contract_error("runner identity changed during stop", INVALID_RECORD)
        if outcome == "stopped":
            return _finish_stop_locked(project, current)
        code = f"runner_stop_{outcome}"
        if current.error_code == code:
            return current
        return _append_from(
            project,
            current,
            RenderJobStatus.RUNNING,
            stage=current.stage,
            error_code=code,
            error_message="runner stop is unconfirmed; PID retained for retry",
        )


def _finish_stop_locked(project: Project, head: RenderJobRecord) -> RenderJobRecord:
    cancelled = head.stage == CANCELLATION_REQUESTED
    artifacts, completed = _best_effort_progress(project, head.job_id)
    return _append_from(
        project,
        head,
        RenderJobStatus.CANCELLED if cancelled else RenderJobStatus.FAILED,
        stage="cancelled" if cancelled else "failed",
        stage_index=completed,
        completed_artifacts=artifacts,
        runner_pid=None,
        error_code=None if cancelled else "terminated",
        error_message=None if cancelled else "runner terminated by request",
    )


def start_render_job(project: Project, job_id: str) -> RenderJobRecord:
    """Spawn the detached runner for ``job_id``, persist RUNNING with its PID, and return; the child owns its own terminal transition."""
    _require_job_id(job_id)
    proc = None
    try:
        with _project_lock(project):
            head = _job_heads(project).get(job_id)
            if head is None or not can_transition_job(head.status, RenderJobStatus.RUNNING):
                raise contract_error("render job cannot be started in its current state", INVALID_RECORD)
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
            return _append_from(project, head, RenderJobStatus.RUNNING, runner_pid=proc.pid, stage="running")
    except BaseException:
        if proc is not None:
            # This is our newly spawned child, which cannot render before RUNNING
            # contains its PID. A failed persistence must not leave it detached.
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                proc.kill()
                proc.wait(timeout=DEFAULT_RENDER_STOP_TIMEOUT)
        raise


def reconcile_render_jobs(project: Project, *, is_alive: Callable[[int], bool] | None = None) -> list[RenderJobRecord]:
    """Finalize only observably quiescent groups with no held lease. An optional
    positive liveness hint preserves an ordinary RUNNING job; a negative hint
    never substitutes for proof that descendants have stopped. Idempotent."""
    changed: list[RenderJobRecord] = []
    with _project_lock(project):
        for job_id, head in _job_heads(project).items():
            if head.status is not RenderJobStatus.RUNNING:
                continue
            if head.stage in STOP_REQUEST_STAGES:
                if group_quiescent(head.runner_pid) and not _runner_lease_is_held(project, job_id):
                    changed.append(_finish_stop_locked(project, head))
                continue
            if is_alive is not None and head.runner_pid is not None and is_alive(head.runner_pid):
                continue
            if not group_quiescent(head.runner_pid) or _runner_lease_is_held(project, job_id):
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
