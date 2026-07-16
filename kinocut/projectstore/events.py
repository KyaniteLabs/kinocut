"""Durable internal event kernel over the append-only project store (Phase-1, linear only).

A compact monotonic event log layered on the existing ``kernel_event`` JSONL
record kind and the project's exclusive lock. Exactly three event kinds are
admitted (``revision.created``, ``render.completed``, ``quality.gate.failed``);
each carries its required identities and a strictly increasing project-scoped
``event_id``. ``append_event`` and ``event_poll`` are the only entry points; an
internal lock-held build helper (``_build_event_locked``) validates an event
record without appending so a caller can commit it alongside its subject record
through one exception-atomic append transaction (used by the render-job success
transition); ``_append_event_locked`` builds and appends one event in one step.

INTERNAL ONLY: no public MCP/CLI/client surface.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import KernelEventRecord
from kinocut.projectstore.store import (
    Project,
    _project_lock,
    append_record_locked,
    read_records,
)

__all__ = ["append_event", "event_poll"]

# Exactly these event kinds are admitted by the Phase-1 event kernel.
ALLOWED_EVENT_KINDS: tuple[str, ...] = (
    "revision.created",
    "render.completed",
    "quality.gate.failed",
)

# Per-kind required identity fields (must be non-None). The revision event is
# job-agnostic; the render and quality-gate events are job-scoped.
_REQUIRED_IDENTITIES: dict[str, tuple[str, ...]] = {
    "revision.created": ("revision_id",),
    "render.completed": ("job_id", "revision_id"),
    "quality.gate.failed": ("job_id",),
}
_JOB_FORBIDDEN: frozenset[str] = frozenset({"revision.created"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_event_kind(event_kind: Any) -> str:
    if event_kind not in ALLOWED_EVENT_KINDS:
        raise contract_error(f"unsupported event_kind: {event_kind!r}", INVALID_RECORD)
    return event_kind


def _validate_required_identities(event_kind: str, *, revision_id: Any, job_id: Any) -> None:
    for field in _REQUIRED_IDENTITIES[event_kind]:
        value = revision_id if field == "revision_id" else job_id
        if value is None:
            raise contract_error(f"{event_kind} requires a {field}", INVALID_RECORD)
    if event_kind in _JOB_FORBIDDEN and job_id is not None:
        raise contract_error(f"{event_kind} must not carry a job_id", INVALID_RECORD)


def _load_ordered_events(project: Project) -> list[KernelEventRecord]:
    """Read kernel events in append order, failing closed on duplicate/non-monotonic ids.

    The store reader already fails closed on corrupt JSON and cross-project rows;
    this additionally guards the kernel invariant that event ids are unique and
    strictly increasing across the project's history.
    """
    events = read_records(project, "kernel_event")
    seen: set[int] = set()
    previous = 0
    for event in events:
        eid = event.event_id
        if eid in seen:
            raise contract_error("kernel event store has a duplicate event_id", INVALID_RECORD)
        if eid <= previous:
            raise contract_error("kernel event store has a non-monotonic event_id", INVALID_RECORD)
        seen.add(eid)
        previous = eid
    return events


def _next_event_id(project: Project) -> int:
    """Next strictly-monotonic event id; the caller must hold the project lock."""
    events = _load_ordered_events(project)
    return 1 if not events else events[-1].event_id + 1


def _build_event_locked(
    project: Project,
    event_kind: str,
    *,
    edit_project_id: str,
    subject_record_id: str,
    revision_id: str | None = None,
    job_id: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    """Build and validate one event record without appending; caller holds the lock.

    The ``event_id`` is the next strictly-monotonic id at call time. Splitting the
    build from the append lets a multi-record caller (the render-job success
    transition) validate every record first and then commit them through one
    exception-atomic append transaction.
    """
    kind = _validate_event_kind(event_kind)
    _validate_required_identities(kind, revision_id=revision_id, job_id=job_id)
    fields: dict[str, Any] = {
        "event_id": _next_event_id(project),
        "event_kind": kind,
        "edit_project_id": edit_project_id,
        "revision_id": revision_id,
        "job_id": job_id,
        "subject_record_id": subject_record_id,
        "project_id": project.project_id,
        "created_by": created_by,
        "created_at": _now(),
    }
    return validate_record(KernelEventRecord, fields)


def _append_event_locked(
    project: Project,
    event_kind: str,
    *,
    edit_project_id: str,
    subject_record_id: str,
    revision_id: str | None = None,
    job_id: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    """Append one validated event assuming the caller already holds the project lock."""
    return append_record_locked(
        project,
        _build_event_locked(
            project,
            event_kind,
            edit_project_id=edit_project_id,
            subject_record_id=subject_record_id,
            revision_id=revision_id,
            job_id=job_id,
            created_by=created_by,
        ),
    )


def append_event(
    project: Project,
    event_kind: str,
    *,
    edit_project_id: str,
    subject_record_id: str,
    revision_id: str | None = None,
    job_id: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    """Append one validated event under the project lock and return it."""
    with _project_lock(project):
        return _append_event_locked(
            project,
            event_kind,
            edit_project_id=edit_project_id,
            subject_record_id=subject_record_id,
            revision_id=revision_id,
            job_id=job_id,
            created_by=created_by,
        )


def _validate_query_kinds(event_kinds: Any) -> tuple[str, ...] | None:
    if event_kinds is None:
        return None
    if isinstance(event_kinds, (str, bytes)) or not isinstance(event_kinds, Iterable):
        raise contract_error("event_kinds must be an iterable of kinds", INVALID_RECORD)
    kinds = tuple(event_kinds)
    for kind in kinds:
        if kind not in ALLOWED_EVENT_KINDS:
            raise contract_error(f"unsupported event_kind: {kind!r}", INVALID_RECORD)
    return kinds


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def event_poll(
    project: Project,
    after_event_id: int | None = None,
    event_kinds: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[KernelEventRecord]:
    """Return events strictly after ``after_event_id`` in stable event_id order.

    ``after_event_id`` is exclusive; ``event_kinds`` must be a subset of the
    allowed set; a provided ``limit`` must be a positive integer. The underlying
    read fails closed on a duplicate or non-monotonic stored id, so a tampered
    log is never served.
    """
    if after_event_id is not None and not _is_positive_int(after_event_id):
        raise contract_error("after_event_id must be a positive integer", INVALID_RECORD)
    if limit is not None and not _is_positive_int(limit):
        raise contract_error("limit must be a positive integer", INVALID_RECORD)
    kinds = _validate_query_kinds(event_kinds)
    events = sorted(_load_ordered_events(project), key=lambda e: e.event_id)
    if after_event_id is not None:
        events = [e for e in events if e.event_id > after_event_id]
    if kinds is not None:
        allowed = set(kinds)
        events = [e for e in events if e.event_kind in allowed]
    if limit is not None:
        events = events[:limit]
    return events
