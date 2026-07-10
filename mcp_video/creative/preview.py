"""Machine-readable storyboard/timeline previews and exact approval bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .composition import _require_digest, _validated
from .composition_models import (
    CompositionApproval,
    CompositionPlan,
    CompositionPreview,
    StoryboardFrame,
    TimelinePreviewRow,
)
from .models import canonical_digest

_ZERO_SHA256 = "sha256:" + "0" * 64


def build_composition_preview(
    plan: CompositionPlan | Mapping[str, Any],
) -> CompositionPreview:
    """Describe the storyboard and timeline without generating preview media."""

    valid_plan = _validated(plan, CompositionPlan)
    _require_digest(valid_plan, "plan_sha256", "composition_plan_hash_mismatch")
    storyboard = tuple(
        StoryboardFrame(
            index=index,
            segment_id=segment.id,
            output_start_seconds=segment.output_start_seconds,
            output_end_seconds=segment.output_end_seconds,
            source_labels=(f"{segment.asset_id}#{segment.selected_span_ids[0]}",),
            layout_id=segment.layout_id,
            graphic_ids=tuple(
                graphic.id
                for graphic in valid_plan.graphics
                if graphic.start_seconds < segment.output_end_seconds
                and graphic.end_seconds > segment.output_start_seconds
            ),
        )
        for index, segment in enumerate(valid_plan.timeline)
    )
    timeline = tuple(
        TimelinePreviewRow(
            segment_id=segment.id,
            output_start_seconds=segment.output_start_seconds,
            output_end_seconds=segment.output_end_seconds,
            selected_span_ids=segment.selected_span_ids,
            audio_track_ids=tuple(
                track.id
                for track in valid_plan.audio_tracks
                if track.output_start_seconds < segment.output_end_seconds
                and track.output_end_seconds > segment.output_start_seconds
            ),
            caption_id=valid_plan.caption_plan.id if valid_plan.caption_plan else None,
        )
        for segment in valid_plan.timeline
    )
    changes = (
        {"kind": "timeline", "description": f"{len(timeline)} approved source-backed segment(s)."},
        {"kind": "graphics", "description": f"{len(valid_plan.graphics)} declared graphic element(s)."},
        {"kind": "audio", "description": f"{len(valid_plan.audio_tracks)} declared audio track(s)."},
        {"kind": "variants", "description": f"{len(valid_plan.output_variants)} output variant(s)."},
    )
    draft = CompositionPreview(
        plan_sha256=valid_plan.plan_sha256,
        storyboard=storyboard,
        timeline=timeline,
        changes=changes,
        preview_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"preview_sha256": canonical_digest(draft, exclude={"preview_sha256"})})


def bind_composition_approval(
    preview: CompositionPreview | Mapping[str, Any],
) -> CompositionApproval:
    """Bind approval to one exact plan, preview, and segment set."""

    valid_preview = _validated(preview, CompositionPreview)
    _require_digest(valid_preview, "preview_sha256", "composition_preview_hash_mismatch")
    draft = CompositionApproval(
        plan_sha256=valid_preview.plan_sha256,
        preview_sha256=valid_preview.preview_sha256,
        approved_segment_ids=tuple(row.segment_id for row in valid_preview.timeline),
        approval_sha256=_ZERO_SHA256,
    )
    return draft.model_copy(update={"approval_sha256": canonical_digest(draft, exclude={"approval_sha256"})})
