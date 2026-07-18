"""Durable poll-first audit events and at-least-once consumer cursors.

Events are append-only, project-scoped, strictly monotonic, and internal only.
Consumers explicitly acknowledge a contiguous event watermark; a crash before
acknowledgement therefore redelivers the same records.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import EventCursorRecord, KernelEventRecord
from kinocut.projectstore.store import Project, _project_lock, append_record_locked, read_records

__all__ = [
    "ack_events",
    "append_event",
    "event_poll",
    "get_event_cursor",
    "poll_for_consumer",
    "sanitize_event_summary",
]

ALLOWED_EVENT_KINDS: tuple[str, ...] = (
    "revision.created",
    "render.queued",
    "render.started",
    "render.completed",
    "render.failed",
    "render.cancelled",
    "quality.gate.passed",
    "quality.gate.failed",
    "branch.created",
    "dag.compiled",
)
_REQUIRED_IDENTITIES: dict[str, tuple[str, ...]] = {
    "revision.created": ("revision_id",),
    "render.queued": ("job_id", "revision_id"),
    "render.started": ("job_id", "revision_id"),
    "render.completed": ("job_id", "revision_id"),
    "render.failed": ("job_id", "revision_id"),
    "render.cancelled": ("job_id", "revision_id"),
    "quality.gate.passed": ("job_id",),
    "quality.gate.failed": ("job_id",),
    "branch.created": (),
    "dag.compiled": ("revision_id",),
}
_JOB_FORBIDDEN = frozenset({"revision.created", "branch.created", "dag.compiled"})
_ABSOLUTE_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/|~/)[^\s:'\"<>]+")
_SECRET_RE = re.compile(r"(?i)\b(?:authorization|api[_-]?key|token|password|secret)\b\s*[:=]\s*[^\r\n]*")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_SUMMARY_CAP = 200


def _now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_event_summary(summary: str | None) -> str | None:
    """Return a bounded audit note with paths, secrets, and controls removed."""
    if summary is None:
        return None
    if not isinstance(summary, str):
        raise contract_error("event summary must be a string", INVALID_RECORD)
    safe = _CONTROL_RE.sub(" ", summary)
    safe = _SECRET_RE.sub("<redacted-secret>", safe)
    safe = _ABSOLUTE_PATH_RE.sub("<redacted-path>", safe)
    return safe[:_SUMMARY_CAP]


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
    """Load in append order and fail closed on duplicate or non-monotonic ids."""
    events = read_records(project, "kernel_event")
    previous = 0
    seen: set[int] = set()
    for event in events:
        if event.event_id in seen:
            raise contract_error("kernel event store has a duplicate event_id", INVALID_RECORD)
        if event.event_id <= previous:
            raise contract_error("kernel event store has a non-monotonic event_id", INVALID_RECORD)
        seen.add(event.event_id)
        previous = event.event_id
    return events


def _next_event_id(project: Project) -> int:
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
    summary: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    """Build the next event without appending; caller holds the project lock."""
    kind = _validate_event_kind(event_kind)
    _validate_required_identities(kind, revision_id=revision_id, job_id=job_id)
    return validate_record(
        KernelEventRecord,
        {
            "event_id": _next_event_id(project),
            "event_kind": kind,
            "edit_project_id": edit_project_id,
            "revision_id": revision_id,
            "job_id": job_id,
            "subject_record_id": subject_record_id,
            "summary": sanitize_event_summary(summary),
            "project_id": project.project_id,
            "created_by": created_by,
            "created_at": _now(),
        },
    )


def _append_event_locked(
    project: Project,
    event_kind: str,
    *,
    edit_project_id: str,
    subject_record_id: str,
    revision_id: str | None = None,
    job_id: str | None = None,
    summary: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    return append_record_locked(
        project,
        _build_event_locked(
            project,
            event_kind,
            edit_project_id=edit_project_id,
            subject_record_id=subject_record_id,
            revision_id=revision_id,
            job_id=job_id,
            summary=summary,
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
    summary: str | None = None,
    created_by: str = "agent",
) -> KernelEventRecord:
    with _project_lock(project):
        return _append_event_locked(
            project,
            event_kind,
            edit_project_id=edit_project_id,
            subject_record_id=subject_record_id,
            revision_id=revision_id,
            job_id=job_id,
            summary=summary,
            created_by=created_by,
        )


def _validate_query_kinds(event_kinds: Any) -> tuple[str, ...] | None:
    if event_kinds is None:
        return None
    if isinstance(event_kinds, (str, bytes)) or not isinstance(event_kinds, Iterable):
        raise contract_error("event_kinds must be an iterable of kinds", INVALID_RECORD)
    kinds = tuple(event_kinds)
    for kind in kinds:
        _validate_event_kind(kind)
    return kinds


def _is_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def event_poll(
    project: Project,
    after_event_id: int | None = None,
    event_kinds: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[KernelEventRecord]:
    """Return stable ordered events after the exclusive caller watermark."""
    if after_event_id is not None and (not _is_nonnegative_int(after_event_id) or after_event_id == 0):
        raise contract_error("after_event_id must be a positive integer", INVALID_RECORD)
    if limit is not None and (not _is_nonnegative_int(limit) or limit == 0):
        raise contract_error("limit must be a positive integer", INVALID_RECORD)
    kinds = _validate_query_kinds(event_kinds)
    events = _load_ordered_events(project)
    if after_event_id is not None:
        events = [event for event in events if event.event_id > after_event_id]
    if kinds is not None:
        allowed = set(kinds)
        events = [event for event in events if event.event_kind in allowed]
    return events if limit is None else events[:limit]


def _cursor_heads(project: Project) -> dict[str, EventCursorRecord]:
    records = read_records(project, "event_cursor")
    superseded = {record.supersedes for record in records if record.supersedes is not None}
    heads: dict[str, EventCursorRecord] = {}
    for record in records:
        if record.record_id in superseded:
            continue
        if record.consumer_id in heads:
            raise contract_error("event consumer has ambiguous cursor heads", INVALID_RECORD)
        heads[record.consumer_id] = record
    return heads


def get_event_cursor(project: Project, consumer_id: str) -> EventCursorRecord | None:
    """Return one consumer's active cursor, or ``None`` before its first ack."""
    validate_record(
        EventCursorRecord,
        {
            "consumer_id": consumer_id,
            "ack_event_id": 0,
            "project_id": project.project_id,
            "created_by": "agent",
        },
    )
    return _cursor_heads(project).get(consumer_id)


def poll_for_consumer(
    project: Project,
    consumer_id: str,
    *,
    event_kinds: Iterable[str] | None = None,
    limit: int | None = None,
) -> list[KernelEventRecord]:
    with _project_lock(project):
        cursor = get_event_cursor(project, consumer_id)
        if cursor is None:
            cursor = append_record_locked(
                project,
                validate_record(
                    EventCursorRecord,
                    {
                        "consumer_id": consumer_id,
                        "ack_event_id": 0,
                        "project_id": project.project_id,
                        "created_by": "agent",
                        "created_at": _now(),
                    },
                ),
            )
        return event_poll(
            project,
            after_event_id=None if cursor.ack_event_id == 0 else cursor.ack_event_id,
            event_kinds=event_kinds,
            limit=limit,
        )


def ack_events(
    project: Project,
    consumer_id: str,
    through_event_id: int,
    *,
    created_by: str = "agent",
) -> EventCursorRecord:
    """Persist a consumer watermark; advancing past a missing event fails closed."""
    if not _is_nonnegative_int(through_event_id):
        raise contract_error("through_event_id must be a non-negative integer", INVALID_RECORD)
    with _project_lock(project):
        current = get_event_cursor(project, consumer_id)
        current_id = 0 if current is None else current.ack_event_id
        if through_event_id < current_id:
            raise contract_error("event cursor cannot move backwards", INVALID_RECORD)
        if through_event_id == current_id and current is not None:
            return current
        events = _load_ordered_events(project)
        if through_event_id != 0 and through_event_id not in {event.event_id for event in events}:
            raise contract_error("cannot acknowledge a missing event", INVALID_RECORD)
        cursor = validate_record(
            EventCursorRecord,
            {
                "consumer_id": consumer_id,
                "ack_event_id": through_event_id,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
                **({"supersedes": current.record_id} if current is not None else {}),
            },
        )
        return append_record_locked(project, cursor)
