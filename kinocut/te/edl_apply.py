"""Human-gated EDL apply: approved delete ids → keep-range trim/merge (N4)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from kinocut.errors import MCPVideoError
from kinocut.ffmpeg_helpers import _validate_input_path, _validate_output_path
from kinocut.semantic.edl import EditApproval, EditDecisionList, EditOperation


def render_approved_edl(
    input_path: str,
    *,
    edl: dict[str, Any],
    approval: dict[str, Any],
    output_path: str,
    source_duration: float | None = None,
) -> dict[str, Any]:
    """Render keep-ranges after an ``EditApproval``. Never applies without approval."""
    src = _validate_input_path(input_path)
    out = _validate_output_path(output_path)
    decision = EditDecisionList.model_validate(edl)
    grant = EditApproval.model_validate(approval)
    if grant.edl_sha256 != decision.edl_sha256:
        raise MCPVideoError(
            "approval does not match this EDL",
            error_type="validation_error",
            code="edl_approval_mismatch",
        )
    if not grant.selected_edit_ids:
        raise MCPVideoError(
            "approval selected_edit_ids is empty",
            error_type="validation_error",
            code="edl_nothing_selected",
        )
    duration = float(source_duration or decision.source_duration_seconds)
    removed = _selected_deletes(decision, grant)
    keep = _invert_ranges(removed, duration)
    if not keep:
        raise MCPVideoError("approved deletes leave no media", error_type="validation_error", code="edl_empty_keep")
    written = _concat_keeps(src, keep, out)
    return {
        "artifact_kind": "edl_render",
        "output_path": written,
        "keep_segments": [{"start": a, "end": b} for a, b in keep],
        "applied_edit_ids": list(grant.selected_edit_ids),
        "edl_sha256": decision.edl_sha256,
        "approval_sha256": grant.approval_sha256,
        "next_action": "quality_check_then_human_review",
    }


def _selected_deletes(edl: EditDecisionList, approval: EditApproval) -> list[tuple[float, float]]:
    wanted = set(approval.selected_edit_ids)
    removed: list[tuple[float, float]] = []
    for edit in edl.edits:
        if edit.edit_id not in wanted:
            continue
        if edit.operation != EditOperation.DELETE:
            raise MCPVideoError(
                f"only delete edits can render in this apply path ({edit.operation})",
                error_type="validation_error",
                code="edl_op_unsupported",
            )
        removed.append((float(edit.source_start_seconds), float(edit.source_end_seconds)))
    if not removed:
        raise MCPVideoError(
            "no approved delete edits to apply",
            error_type="validation_error",
            code="edl_no_deletes",
        )
    return removed


def _invert_ranges(removed: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    ordered = sorted(removed)
    keep: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in ordered:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))
    return [(a, b) for a, b in keep if b - a > 1e-3]


def _concat_keeps(src: str, keep: list[tuple[float, float]], out: str) -> str:
    from kinocut.engine_edit import trim
    from kinocut.engine_merge import merge

    if len(keep) == 1:
        start, end = keep[0]
        return trim(src, start=start, duration=end - start, output_path=out, accurate=True).output_path
    tmp = tempfile.mkdtemp(prefix="kinocut_edl_")
    parts: list[str] = []
    for i, (start, end) in enumerate(keep):
        part = os.path.join(tmp, f"k{i:03d}.mp4")
        parts.append(trim(src, start=start, duration=end - start, output_path=part, accurate=True).output_path)
    return merge(parts, output_path=out).output_path
