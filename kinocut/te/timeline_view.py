"""Agent-visible timeline text from a SemanticTimeline or span dicts (N2)."""

from __future__ import annotations

from typing import Any

from kinocut.errors import MCPVideoError


def render_timeline_text(
    timeline: dict[str, Any] | None = None,
    *,
    spans: list[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Render a scannable text score (shots / silence / words).

    Accepts a SemanticTimeline dump or a flat ``spans`` list with
    ``kind``, ``start``, ``end``, and optional ``label``.
    """
    rows = _collect_rows(timeline, spans)
    if not rows:
        raise MCPVideoError(
            "timeline has no spans to render",
            error_type="validation_error",
            code="empty_timeline",
        )
    dur = duration_seconds
    if dur is None and timeline and isinstance(timeline.get("source"), dict):
        dur = float(timeline["source"].get("duration_seconds") or 0) or None
    if dur is None:
        dur = max(r["end"] for r in rows)
    lines = [f"t={r['start']:.2f}-{r['end']:.2f} [{r['kind']}] {r['label']}" for r in rows]
    return {
        "artifact_kind": "timeline_view",
        "duration_seconds": dur,
        "row_count": len(rows),
        "spans": rows,
        "text": "\n".join(lines),
        "next_action": "use_timestamps_in_trim_or_cutfile",
    }


def _collect_rows(
    timeline: dict[str, Any] | None,
    spans: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = list(spans or [])
    if isinstance(timeline, dict):
        for key in ("shots", "scenes", "silences", "words", "speakers", "audio_events", "keyframes"):
            for item in timeline.get(key) or []:
                if isinstance(item, dict):
                    raw.append(item)
    rows: list[dict[str, Any]] = []
    for item in raw:
        start = item.get("source_start_seconds", item.get("start"))
        end = item.get("source_end_seconds", item.get("end"))
        if start is None or end is None:
            continue
        kind = str(item.get("kind") or "span")
        label = item.get("text") or item.get("label") or item.get("speaker_label") or kind
        rows.append({"kind": kind, "start": float(start), "end": float(end), "label": str(label)})
    rows.sort(key=lambda r: (r["start"], r["end"], r["kind"]))
    return rows
