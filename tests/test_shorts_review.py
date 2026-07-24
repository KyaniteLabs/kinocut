from __future__ import annotations

from pathlib import Path

import pytest

from kinocut.errors import MCPVideoError
from kinocut.product.models import CandidateMoment, TranscriptSegment, canonical_dedup_key
from kinocut.product.shorts_plan import IntakeReport, ShortsPlan, load_shorts_plan, save_shorts_plan
from kinocut.product.shorts_review import resolve_approved_candidate, review_shorts_plan


def _candidate(**updates) -> CandidateMoment:
    values = {
        "candidate_id": "candidate_01",
        "start": 10.0,
        "end": 25.0,
        "transcript_excerpt": "A complete candidate thought.",
        "suggested_title": "A useful clip",
        "suggested_hook": "Start here",
        "rationale": "Complete thought",
        "confidence": 0.9,
        "sensitivity": "none",
        "unsuitable": False,
    }
    values.update(updates)
    values["dedup_key"] = canonical_dedup_key(
        start=values["start"],
        end=values["end"],
        excerpt=values["transcript_excerpt"],
        sensitivity=values["sensitivity"],
    )
    return CandidateMoment.model_validate(values)


def _plan(output_dir: Path, **updates) -> ShortsPlan:
    values = {
        "job_id": "shorts_0123456789abcdef",
        "project_dir": str(output_dir.parent),
        "output_dir": str(output_dir),
        "intake": IntakeReport(
            source_path="/tmp/source.mp4",
            source_sha256="0" * 64,
            duration=60.0,
            width=1920,
            height=1080,
            audio_available=True,
        ),
        "platforms": ("youtube-shorts", "instagram-reel"),
        "config": {},
        "transcript": (TranscriptSegment(segment_id="segment_01", start=0.0, end=30.0, text="Transcript"),),
        "proposals": (_candidate(),),
    }
    values.update(updates)
    return ShortsPlan.model_validate(values)


def test_review_appends_decision_and_persists(tmp_path):
    plan = _plan(tmp_path / "plans")
    save_shorts_plan(plan)
    revised = review_shorts_plan(
        str(tmp_path / "plans"),
        candidate_id="candidate_01",
        decision="approve",
    )
    assert revised.status == "reviewed"
    assert len(revised.decisions) == 1
    assert revised.decisions[0].action == "approve"
    reloaded = load_shorts_plan(str(tmp_path / "plans"))
    assert reloaded == revised


def test_review_rejects_unknown_candidate(tmp_path):
    save_shorts_plan(_plan(tmp_path / "plans"))
    with pytest.raises(MCPVideoError) as exc:
        review_shorts_plan(str(tmp_path / "plans"), candidate_id="missing", decision="approve")
    assert exc.value.code == "shorts_candidate_not_found"


def test_review_rejects_invalid_action_shape(tmp_path):
    save_shorts_plan(_plan(tmp_path / "plans"))
    with pytest.raises(MCPVideoError) as exc:
        review_shorts_plan(
            str(tmp_path / "plans"),
            candidate_id="candidate_01",
            decision={"action": "approve", "title": "not allowed"},
        )
    assert exc.value.code == "shorts_review_invalid"


def test_resolve_requires_current_approve(tmp_path):
    plan = save_shorts_plan(_plan(tmp_path / "plans"))
    with pytest.raises(MCPVideoError) as exc:
        resolve_approved_candidate(plan, "candidate_01")
    assert exc.value.code == "shorts_review_required"

    approved = review_shorts_plan(str(tmp_path / "plans"), candidate_id="candidate_01", decision="approve")
    effective = resolve_approved_candidate(approved, "candidate_01")
    assert effective.candidate_id == "candidate_01"

    rejected = review_shorts_plan(str(tmp_path / "plans"), candidate_id="candidate_01", decision="reject")
    with pytest.raises(MCPVideoError) as exc:
        resolve_approved_candidate(rejected, "candidate_01")
    assert exc.value.code == "shorts_review_required"


def test_resolve_applies_trim_and_title_edits(tmp_path):
    save_shorts_plan(_plan(tmp_path / "plans"))
    review_shorts_plan(
        str(tmp_path / "plans"),
        candidate_id="candidate_01",
        decision={"action": "trim", "start": 12.0, "end": 22.0},
    )
    review_shorts_plan(
        str(tmp_path / "plans"),
        candidate_id="candidate_01",
        decision={"action": "title_hook_edit", "title": "New title", "hook": "New hook"},
    )
    plan = review_shorts_plan(str(tmp_path / "plans"), candidate_id="candidate_01", decision="approve")
    effective = resolve_approved_candidate(plan, "candidate_01")
    assert effective.start == 12.0
    assert effective.end == 22.0
    assert effective.suggested_title == "New title"
    assert effective.suggested_hook == "New hook"
    assert effective.dedup_key == canonical_dedup_key(
        start=12.0,
        end=22.0,
        excerpt=effective.transcript_excerpt,
        sensitivity="none",
    )


def test_resolve_blocks_unsuitable_even_if_approved(tmp_path):
    save_shorts_plan(_plan(tmp_path / "plans"))
    review_shorts_plan(str(tmp_path / "plans"), candidate_id="candidate_01", decision="approve")
    plan = review_shorts_plan(
        str(tmp_path / "plans"),
        candidate_id="candidate_01",
        decision={"action": "sensitive_unsuitable", "unsuitable": True},
    )
    with pytest.raises(MCPVideoError) as exc:
        resolve_approved_candidate(plan, "candidate_01")
    assert exc.value.code == "shorts_candidate_unsuitable"
