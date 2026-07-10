from __future__ import annotations

import pytest
from pydantic import ValidationError

from mcp_video.errors import MCPVideoError
from mcp_video.semantic.edl import (
    EditApproval,
    EditOperation,
    approve_edl,
    create_edl,
    make_edit,
    plan_timeline_diff,
    verify_timeline_diff,
)
from mcp_video.semantic.models import AnalyzerProvenance, SemanticTimeline, ShotSpan, SourceMedia, WordSpan


def _timeline() -> SemanticTimeline:
    source = SourceMedia.create(content_sha256="sha256:" + "3" * 64, duration_seconds=4)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.timeline",
        analyzer_version="1",
        model_id="fixture",
        model_sha256="sha256:" + "4" * 64,
        determinism_scope="fixture",
    )
    shots = (
        ShotSpan.create(source=source, start_seconds=0, end_seconds=2, confidence=1, provenance=provenance, ordinal=0),
        ShotSpan.create(source=source, start_seconds=2, end_seconds=4, confidence=1, provenance=provenance, ordinal=1),
    )
    filler = WordSpan.create(
        source=source,
        start_seconds=1,
        end_seconds=1.2,
        confidence=0.98,
        provenance=provenance,
        text="um",
        disfluency="filler",
    )
    retained = WordSpan.create(
        source=source,
        start_seconds=2.5,
        end_seconds=2.8,
        confidence=0.95,
        provenance=provenance,
        text="keep",
    )
    return SemanticTimeline.create(source=source, words=(filler, retained), shots=shots)


def test_edl_diff_binds_exact_edits_and_verifies_source_coverage() -> None:
    timeline = _timeline()
    word = timeline.words[0]
    edit = make_edit(operation=EditOperation.DELETE, target_span=word, rationale="remove confirmed filler")
    edl = create_edl(timeline, edits=(edit,))
    approval = approve_edl(edl, selected_edit_ids=(edit.edit_id,))

    diff = plan_timeline_diff(timeline, edl, approval)
    verification = verify_timeline_diff(timeline, edl, approval, diff)

    assert edl.edl_sha256.startswith("sha256:")
    assert edit.edit_id.startswith("edit:")
    assert approval.edl_sha256 == edl.edl_sha256
    assert approval.selected_edit_ids == (edit.edit_id,)
    assert edl.timeline_edits_allowed
    assert not edl.synthetic_speech_allowed
    assert not edl.hidden_reordering_allowed
    assert not edl.source_overwrite_allowed
    assert not edl.network_allowed
    assert diff.removed[0].source_start_seconds == 1
    assert diff.removed[0].source_end_seconds == 1.2
    assert diff.output_duration_seconds == pytest.approx(3.8)
    assert diff.audio_video_mapping_shared
    assert diff.caption_remap[0].span_id == timeline.words[1].span_id
    assert diff.caption_remap[0].output_start_seconds == pytest.approx(2.3)
    assert verification.passed
    assert {check.check_id for check in verification.checks} >= {
        "approval_hash",
        "source_coverage",
        "ordering",
        "approved_removal_only",
        "audio_video_sync",
        "caption_remap",
    }


def test_approval_and_diff_tampering_fail_closed() -> None:
    timeline = _timeline()
    edit = make_edit(operation=EditOperation.DELETE, target_span=timeline.words[0], rationale="confirmed")
    edl = create_edl(timeline, edits=(edit,))
    approval = approve_edl(edl, selected_edit_ids=(edit.edit_id,))

    payload = approval.model_dump(mode="json")
    payload["selected_edit_ids"] = []
    with pytest.raises(ValidationError, match="approval hash"):
        EditApproval.model_validate(payload)

    forged_approval = approval.model_copy(update={"selected_edit_ids": ()})
    with pytest.raises(MCPVideoError, match="approval hash"):
        plan_timeline_diff(timeline, edl, forged_approval)

    diff = plan_timeline_diff(timeline, edl, approval)
    forged = diff.model_copy(update={"output_duration_seconds": 1.0})
    report = verify_timeline_diff(timeline, edl, approval, forged)
    assert not report.passed
    assert not next(check for check in report.checks if check.check_id == "approved_removal_only").passed


def test_overlapping_edit_intents_are_rejected_as_ambiguous() -> None:
    timeline = _timeline()
    delete = make_edit(operation=EditOperation.DELETE, target_span=timeline.shots[0], rationale="delete shot")
    reorder = make_edit(
        operation=EditOperation.REORDER,
        target_span=timeline.shots[0],
        destination_index=0,
        rationale="move same shot",
    )

    with pytest.raises(MCPVideoError, match="must not overlap"):
        create_edl(timeline, edits=(delete, reorder))


def test_approved_reorder_is_visible_in_output_order() -> None:
    timeline = _timeline()
    move = make_edit(
        operation=EditOperation.REORDER,
        target_span=timeline.shots[1],
        destination_index=0,
        rationale="place second shot first",
    )
    edl = create_edl(timeline, edits=(move,))
    approval = approve_edl(edl, selected_edit_ids=(move.edit_id,))

    diff = plan_timeline_diff(timeline, edl, approval)

    assert [(segment.source_start_seconds, segment.source_end_seconds) for segment in diff.output_segments] == [
        (2.0, 4.0),
        (0.0, 2.0),
    ]
    assert verify_timeline_diff(timeline, edl, approval, diff).passed
