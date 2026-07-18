"""Crash-safe bounded retention for the durable audit event log."""

from __future__ import annotations

from datetime import UTC, datetime

from kinocut.contracts._errors import INVALID_RECORD, contract_error
from kinocut.contracts.adapter import validate_record
from kinocut.contracts.trusted_execution import EventRetentionRecord
from kinocut.projectstore import layout
from kinocut.projectstore.events import _cursor_heads, _load_ordered_events
from kinocut.projectstore.store import (
    Project,
    _canonical_line,
    _mapped_os_errors,
    _project_lock,
    _write_atomically,
    append_record_locked,
    safe_target,
)

__all__ = ["retain_events"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def retain_events(
    project: Project,
    *,
    max_events: int,
    created_by: str = "agent",
) -> EventRetentionRecord:
    """Keep at most ``max_events`` when every cursor safely permits the prefix prune.

    A registered consumer is never stranded: only events at or below the minimum
    acknowledged watermark are eligible. The event rewrite and receipt append are
    exception-atomic from the caller's perspective; a receipt failure restores the
    exact prior log bytes.
    """
    if not isinstance(max_events, int) or isinstance(max_events, bool) or max_events < 1:
        raise contract_error("max_events must be a positive integer", INVALID_RECORD)

    with _project_lock(project):
        events = _load_ordered_events(project)
        cursors = _cursor_heads(project)
        latest = events[-1].event_id if events else 0
        watermark = min((cursor.ack_event_id for cursor in cursors.values()), default=latest)
        desired_prune = max(0, len(events) - max_events)
        eligible_prune = sum(event.event_id <= watermark for event in events)
        prune_count = min(desired_prune, eligible_prune)
        pruned = events[:prune_count]
        survivors = events[prune_count:]
        pruned_max = pruned[-1].event_id if pruned else 0
        surviving_min = survivors[0].event_id if survivors else None
        keep_from = surviving_min if surviving_min is not None else max(latest + 1, 1)
        receipt = validate_record(
            EventRetentionRecord,
            {
                "keep_from_event_id": keep_from,
                "pruned_count": prune_count,
                "pruned_max_event_id": pruned_max,
                "watermark_event_id": watermark,
                "surviving_min_event_id": surviving_min,
                "project_id": project.project_id,
                "created_by": created_by,
                "created_at": _now(),
            },
        )
        event_path = safe_target(project, layout.records_relative_path("kernel_event"))
        with _mapped_os_errors():
            prior = event_path.read_bytes() if event_path.exists() else None
        payload = "".join(_canonical_line(event.model_dump(mode="json")) + "\n" for event in survivors)
        try:
            if prune_count:
                _write_atomically(event_path, lambda handle: handle.write(payload))
            return append_record_locked(project, receipt)
        except BaseException:
            if prune_count:
                if prior is None:
                    with _mapped_os_errors():
                        event_path.unlink(missing_ok=True)
                else:
                    _write_atomically(event_path, lambda handle: handle.write(prior), binary=True)
            raise
