"""Explicit review and durable compilation of semantic disfluency cuts."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise

from pydantic import Field

from kinocut.contracts._common import Sha256, ValueObject
from kinocut.errors import ValidationError as MCPValidationError
from kinocut.semantic.edl import EditApproval, EditDecisionList, EditOperation
from kinocut.semantic.models import SemanticTimeline

from .compat import compile_operations, compile_repurpose_slice
from .store import Project


class DisfluencyCutPlan(ValueObject):
    semantic_timeline_sha256: Sha256
    edl_sha256: Sha256
    approval_sha256: Sha256
    selected_edit_ids: tuple[str, ...] = Field(min_length=1)
    source_digest: Sha256
    keep_segments: tuple[tuple[float, float], ...] = Field(min_length=1)
    operation_id: Sha256


def compile_disfluency_cut_plan(
    *,
    timeline: SemanticTimeline,
    edl: EditDecisionList,
    selected_edit_ids: Sequence[str],
    source_digest: str,
) -> DisfluencyCutPlan:
    """Compile explicit selections to one typed cut plan without mutating a project."""

    if edl.semantic_timeline_sha256 != timeline.timeline_sha256:
        raise MCPValidationError("edl", "must reference the exact semantic timeline")
    approval = EditApproval.create(edl=edl, selected_edit_ids=selected_edit_ids)
    selected = [edit for edit in edl.edits if edit.edit_id in approval.selected_edit_ids]
    if any(edit.operation is not EditOperation.DELETE for edit in selected):
        raise MCPValidationError("selected_edit_ids", "disfluency cuts may select only delete proposals")
    removed = _merge_ranges((edit.source_start_seconds, edit.source_end_seconds) for edit in selected)
    keep = _invert_ranges(removed, timeline.source.duration_seconds)
    if not keep:
        raise MCPValidationError("selected_edit_ids", "cuts may not remove the entire source")
    descriptor = {"kind": "silence_cut", "source": source_digest, "keep_segments": keep}
    operation_id = compile_operations((descriptor,))[0]
    return DisfluencyCutPlan(
        semantic_timeline_sha256=timeline.timeline_sha256,
        edl_sha256=edl.edl_sha256,
        approval_sha256=approval.approval_sha256,
        selected_edit_ids=approval.selected_edit_ids,
        source_digest=source_digest,
        keep_segments=keep,
        operation_id=operation_id,
    )


def apply_disfluency_cut_plan(
    project: Project,
    edit_project_id: str,
    plan: DisfluencyCutPlan,
    *,
    base_revision_id: str | None = None,
):
    """Append one revision from an already-reviewed plan; never select edits implicitly."""

    descriptor = {
        "kind": "silence_cut",
        "source": plan.source_digest,
        "keep_segments": plan.keep_segments,
    }
    if compile_operations((descriptor,))[0] != plan.operation_id:
        raise MCPValidationError("plan", "operation identity does not match the reviewed cut plan")
    return compile_repurpose_slice(project, edit_project_id, (descriptor,), base_revision_id=base_revision_id)


def _merge_ranges(ranges: Iterable[tuple[float, float]]) -> tuple[tuple[float, float], ...]:
    ordered = sorted(ranges)
    if not ordered:
        raise MCPValidationError("selected_edit_ids", "at least one proposal must be selected")
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        previous_start, previous_end = merged[-1]
        if start <= previous_end:
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _invert_ranges(
    removed: tuple[tuple[float, float], ...],
    duration: float,
) -> tuple[tuple[float, float], ...]:
    keep = []
    cursor = 0.0
    for start, end in removed:
        if start > cursor:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < duration:
        keep.append((cursor, duration))
    if any(current[0] < previous[1] for previous, current in pairwise(keep)):
        raise MCPValidationError("selected_edit_ids", "compiled keep ranges overlap")
    return tuple(keep)


__all__ = ["DisfluencyCutPlan", "apply_disfluency_cut_plan", "compile_disfluency_cut_plan"]
