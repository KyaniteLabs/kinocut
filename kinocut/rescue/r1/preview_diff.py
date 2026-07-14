"""Deterministic preview diffs and exact approval bindings."""

from __future__ import annotations

from .models import ApprovalBinding, PreviewDiff, PreviewPair, Sha256, model_digest


def build_preview_diff(
    *,
    plan_sha256: Sha256,
    selected_action_ids: tuple[str, ...],
    previews: tuple[PreviewPair, ...],
    changes: tuple[dict[str, str], ...],
) -> PreviewDiff:
    draft = PreviewDiff(
        plan_sha256=plan_sha256,
        selected_action_ids=selected_action_ids,
        previews=previews,
        changes=changes,
        diff_sha256="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"diff_sha256": model_digest(draft, exclude={"diff_sha256"})})


def bind_approval(diff: PreviewDiff) -> ApprovalBinding:
    draft = ApprovalBinding(
        plan_sha256=diff.plan_sha256,
        selected_action_ids=diff.selected_action_ids,
        preview_diff_sha256=diff.diff_sha256,
        approval_sha256="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"approval_sha256": model_digest(draft, exclude={"approval_sha256"})})
