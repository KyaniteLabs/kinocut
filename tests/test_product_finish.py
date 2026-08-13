"""Product-finish: goal cutfile, timeline text, receipt diff, EDL apply, solver, session QC."""

from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.semantic.edl import EditOperation, approve_edl, create_edl, make_edit
from kinocut.semantic.models import AnalyzerProvenance, SemanticTimeline, ShotSpan, SourceMedia, WordSpan
from kinocut.te import (
    compile_goal_to_cutfile,
    diff_receipts,
    render_approved_edl,
    render_timeline_text,
    session_open,
    session_step,
    solve_publish_cutfile,
    validate_cutfile,
    validate_publish_spec,
)


def test_goal_compiles_valid_vertical_cutfile() -> None:
    cf = compile_goal_to_cutfile("15s vertical short with captions", source="media/hero.mp4")
    validate_cutfile(cf)
    ops = [o["op"] for o in cf["ops"]]
    assert "trim" in ops
    assert "resize" in ops
    assert "add_text" in ops
    assert any(o.get("duration") == 15 for o in cf["ops"] if o["op"] == "trim")


def test_timeline_text_from_spans() -> None:
    view = render_timeline_text(
        spans=[
            {"kind": "shot", "start": 0, "end": 2, "label": "A"},
            {"kind": "silence", "start": 2, "end": 2.4, "label": "gap"},
        ]
    )
    assert view["row_count"] == 2
    assert "t=0.00-2.00" in view["text"]
    assert "[shot]" in view["text"]


def test_receipt_diff_and_replay_plan() -> None:
    left = {"artifact_kind": "workflow_receipt", "ops": ["trim", "resize"]}
    right = {"artifact_kind": "workflow_receipt", "ops": ["trim", "add_text"]}
    diff = diff_receipts(left, right)
    assert diff["added"] == ["add_text"]
    assert diff["removed"] == ["resize"]
    assert diff["replay"]["dry_run"] is True
    assert diff["changed"] is True


def test_constraint_solver_passes_publish_spec() -> None:
    solved = solve_publish_cutfile("youtube_shorts", source="media/in.mp4", source_duration=120)
    assert solved["ops"]
    proof = solved["publish_proof"]
    assert proof["verdict"] == "pass"
    assert proof["blocked"] is False
    resize = next(o for o in solved["ops"] if o["op"] == "resize")
    check = validate_publish_spec(
        "youtube_shorts",
        duration_seconds=60,
        height=resize["height"],
        width=resize["width"],
    )
    assert check["verdict"] == "pass"


def test_session_step_measures_qc_without_caller_score(tmp_path: Path, sample_video: str) -> None:
    opened = session_open(str(tmp_path / "sess"), "improve")
    stepped = session_step(opened["path"], action="qc", input_path=sample_video)
    assert stepped["current_score"] is not None
    assert stepped["measured_improvement"] == pytest.approx(0.0)


def _tiny_timeline() -> SemanticTimeline:
    source = SourceMedia.create(content_sha256="sha256:" + "a" * 64, duration_seconds=4)
    provenance = AnalyzerProvenance(
        analyzer_id="fixture.timeline",
        analyzer_version="1",
        model_id="fixture",
        model_sha256="sha256:" + "b" * 64,
        determinism_scope="fixture",
    )
    shots = (
        ShotSpan.create(source=source, start_seconds=0, end_seconds=2, confidence=1, provenance=provenance, ordinal=0),
        ShotSpan.create(source=source, start_seconds=2, end_seconds=4, confidence=1, provenance=provenance, ordinal=1),
    )
    filler = WordSpan.create(
        source=source,
        start_seconds=1,
        end_seconds=1.5,
        confidence=1,
        provenance=provenance,
        text="um",
        disfluency="filler",
    )
    return SemanticTimeline.create(source=source, words=(filler,), shots=shots)


def test_edl_apply_requires_approval() -> None:
    timeline = _tiny_timeline()
    edit = make_edit(operation=EditOperation.DELETE, target_span=timeline.words[0], rationale="drop filler")
    edl = create_edl(timeline, edits=(edit,))
    with pytest.raises(Exception):
        render_approved_edl(
            "missing.mp4",
            edl=edl.model_dump(mode="json"),
            approval={"edl_sha256": edl.edl_sha256, "selected_edit_ids": [], "approval_sha256": "sha256:" + "0" * 64},
            output_path="/tmp/out.mp4",
        )


def test_edl_apply_renders_keep_ranges(tmp_path: Path, sample_video: str) -> None:
    timeline = _tiny_timeline()
    edit = make_edit(operation=EditOperation.DELETE, target_span=timeline.words[0], rationale="drop filler")
    edl = create_edl(timeline, edits=(edit,))
    approval = approve_edl(edl, selected_edit_ids=(edit.edit_id,))
    out = tmp_path / "edl.mp4"
    result = render_approved_edl(
        sample_video,
        edl=edl.model_dump(mode="json"),
        approval=approval.model_dump(mode="json"),
        output_path=str(out),
        source_duration=4.0,
    )
    assert Path(result["output_path"]).is_file()
    assert result["applied_edit_ids"] == [edit.edit_id]
    assert result["keep_segments"]


def test_goal_cutfile_is_what_intent_would_attach() -> None:
    from kinocut.intent import route_intent

    plan = route_intent("repurpose")
    cut = compile_goal_to_cutfile("15 second vertical reel")
    assert plan.verb == "repurpose"
    assert cut["artifact_kind"] == "cutfile"
    assert cut["ops"]
