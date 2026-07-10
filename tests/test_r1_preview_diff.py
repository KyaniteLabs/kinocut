from __future__ import annotations

from mcp_video.rescue.r1.models import PreviewPair
from mcp_video.rescue.r1.preview_diff import bind_approval, build_preview_diff


def test_preview_diff_and_approval_are_deterministic(rescue_plan) -> None:
    pair = PreviewPair(
        before_path="preview/before.jpg",
        before_sha256="sha256:" + "1" * 64,
        after_path="preview/after.jpg",
        after_sha256="sha256:" + "2" * 64,
        timestamp_seconds=0.5,
    )

    first = build_preview_diff(
        plan_sha256=rescue_plan.plan_sha256,
        selected_action_ids=("crop:subject",),
        previews=(pair,),
        changes=({"kind": "crop", "description": "Track primary subject."},),
    )
    second = build_preview_diff(
        plan_sha256=rescue_plan.plan_sha256,
        selected_action_ids=("crop:subject",),
        previews=(pair,),
        changes=({"kind": "crop", "description": "Track primary subject."},),
    )

    assert first == second
    approval = bind_approval(first)
    assert approval.plan_sha256 == rescue_plan.plan_sha256
    assert approval.selected_action_ids == ("crop:subject",)
    assert approval.preview_diff_sha256 == first.diff_sha256
