"""Beat map: planned beat requirements bound to an acceptance spec (#42)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.editorial import (
    beat_maps_for_spec,
    continuity_plans_for_spec,
    continuity_assistant,
    coverage_report,
    record_beat_map,
    record_continuity_plan,
)
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.editorial import BeatMap, BeatRequirement, ContinuityExpectation, ContinuityPlan
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import acceptance_spec_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _spec(project, **overrides) -> GenerationAcceptanceSpec:
    return GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project.project_id, **overrides))


def _beat_map(project, spec_id, **overrides) -> BeatMap:
    base = {
        "project_id": project.project_id,
        "created_by": "human",
        "acceptance_spec_id": spec_id,
        "beats": (
            BeatRequirement(beat_id="intro", label="Cold open", required_subjects=("product",)),
            BeatRequirement(beat_id="demo", label="Product demo"),
        ),
    }
    base.update(overrides)
    return BeatMap(**base)


def test_record_beat_map_persists_bound_to_acceptance_spec(project):
    spec = append_record(project, _spec(project))
    stored = record_beat_map(project, _beat_map(project, spec.record_id))
    assert stored.record_kind == "beat_map"
    assert stored.acceptance_spec_id == spec.record_id
    assert [b.beat_id for b in stored.beats] == ["intro", "demo"]
    assert stored.record_id == canonical_record_id(_beat_map(project, spec.record_id))


def test_record_beat_map_rejects_dangling_acceptance_spec(project):
    with pytest.raises(MCPVideoError, match="acceptance spec"):
        record_beat_map(project, _beat_map(project, "sha256:" + "0" * 64))


def test_beat_maps_for_spec_returns_active_only(project):
    spec = append_record(project, _spec(project))
    first = record_beat_map(project, _beat_map(project, spec.record_id))
    record_beat_map(
        project,
        _beat_map(
            project,
            spec.record_id,
            supersedes=first.record_id,
            beats=(BeatRequirement(beat_id="intro", label="Revised open"),),
        ),
    )
    rows = beat_maps_for_spec(project, spec.record_id)
    assert len(rows) == 1
    assert rows[0].beats[0].label == "Revised open"


def test_beat_map_rejects_duplicate_beat_ids(project):
    spec = append_record(project, _spec(project))
    with pytest.raises(Exception, match="unique"):
        record_beat_map(
            project,
            _beat_map(
                project,
                spec.record_id,
                beats=(
                    BeatRequirement(beat_id="intro", label="A"),
                    BeatRequirement(beat_id="intro", label="B"),
                ),
            ),
        )


def _continuity_plan(project, spec_id, **overrides) -> ContinuityPlan:
    base = {
        "project_id": project.project_id,
        "created_by": "human",
        "acceptance_spec_id": spec_id,
        "expectations": (
            ContinuityExpectation(shot_id="shot_a", expected_subjects=("product",)),
            ContinuityExpectation(shot_id="shot_b", forbidden_changes=("wardrobe",)),
        ),
    }
    base.update(overrides)
    return ContinuityPlan(**base)


def test_record_continuity_plan_persists_bound_to_acceptance_spec(project):
    spec = append_record(project, _spec(project))
    stored = record_continuity_plan(project, _continuity_plan(project, spec.record_id))
    assert stored.record_kind == "continuity_plan"
    assert stored.acceptance_spec_id == spec.record_id
    assert [e.shot_id for e in stored.expectations] == ["shot_a", "shot_b"]


def test_record_continuity_plan_rejects_dangling_acceptance_spec(project):
    with pytest.raises(MCPVideoError, match="acceptance spec"):
        record_continuity_plan(project, _continuity_plan(project, "sha256:" + "0" * 64))


def test_continuity_plans_for_spec_returns_active_only(project):
    spec = append_record(project, _spec(project))
    first = record_continuity_plan(project, _continuity_plan(project, spec.record_id))
    record_continuity_plan(
        project,
        _continuity_plan(
            project,
            spec.record_id,
            supersedes=first.record_id,
            expectations=(ContinuityExpectation(shot_id="shot_a", expected_subjects=("product", "logo")),),
        ),
    )
    rows = continuity_plans_for_spec(project, spec.record_id)
    assert len(rows) == 1
    assert rows[0].expectations[0].expected_subjects == ("product", "logo")


def test_continuity_plan_rejects_duplicate_shot_ids(project):
    spec = append_record(project, _spec(project))
    with pytest.raises(Exception, match="unique"):
        record_continuity_plan(
            project,
            _continuity_plan(
                project,
                spec.record_id,
                expectations=(
                    ContinuityExpectation(shot_id="shot_a"),
                    ContinuityExpectation(shot_id="shot_a"),
                ),
            ),
        )


# --- #43 coverage report ---


def _clip(project, **overrides):
    from kinocut.contracts.registry import ClipRecord
    from tests.registry_fixtures import clip_record_kwargs

    return ClipRecord(**clip_record_kwargs(project_id=project.project_id, **overrides))


def test_coverage_report_empty_when_no_beat_map(project):
    spec = append_record(project, _spec(project))
    report = coverage_report(project, spec.record_id)
    assert report.total_beats == 0
    assert report.covered_count == 0
    assert report.beats == ()


def test_coverage_report_covers_beat_whose_subjects_are_in_approved_clip_tags(project):
    spec = append_record(project, _spec(project))
    record_beat_map(
        project,
        _beat_map(
            project,
            spec.record_id,
            beats=(
                BeatRequirement(beat_id="intro", label="Open", required_subjects=("product",)),
                BeatRequirement(beat_id="cta", label="Call to action"),
            ),
        ),
    )
    append_record(project, _clip(project, tags=("product",), source_asset_id="sha256:" + "1" * 64))
    report = coverage_report(project, spec.record_id)
    assert report.total_beats == 2
    assert report.covered_count == 2  # intro has product; cta has no requirements
    assert all(beat.covered for beat in report.beats)
    assert report.approved_clip_count == 1


def test_coverage_report_flags_beat_with_unmet_required_subject(project):
    spec = append_record(project, _spec(project))
    record_beat_map(
        project,
        _beat_map(
            project,
            spec.record_id,
            beats=(
                BeatRequirement(beat_id="logo", label="Logo beat", required_subjects=("logo", "product")),
            ),
        ),
    )
    append_record(project, _clip(project, tags=("product",), source_asset_id="sha256:" + "2" * 64))
    report = coverage_report(project, spec.record_id)
    assert report.total_beats == 1
    assert report.covered_count == 0
    beat = report.beats[0]
    assert beat.covered is False
    assert beat.missing_subjects == ("logo",)


# --- #19 continuity assistant ---


def _continuity_project(project, spec, **plan_overrides):
    record_continuity_plan(project, _continuity_plan(project, spec.record_id, **plan_overrides))


def test_continuity_assistant_satisfied_when_subjects_present_and_no_forbidden(project):
    spec = append_record(project, _spec(project))
    _continuity_project(
        project,
        spec,
        expectations=(ContinuityExpectation(shot_id="shot_a", expected_subjects=("product",)),),
    )
    append_record(project, _clip(project, tags=("product",), source_asset_id="sha256:" + "3" * 64))
    report = continuity_assistant(project, spec.record_id)
    assert report.optional_provider_status == "provider_not_configured"
    assert len(report.findings) == 1
    assert report.findings[0].status == "satisfied"


def test_continuity_assistant_incomplete_when_expected_subject_missing(project):
    spec = append_record(project, _spec(project))
    _continuity_project(
        project,
        spec,
        expectations=(ContinuityExpectation(shot_id="shot_a", expected_subjects=("product", "logo")),),
    )
    append_record(project, _clip(project, tags=("product",), source_asset_id="sha256:" + "4" * 64))
    report = continuity_assistant(project, spec.record_id)
    assert report.findings[0].status == "incomplete"
    assert report.findings[0].unmet_subjects == ("logo",)


def test_continuity_assistant_violation_when_forbidden_change_present(project):
    spec = append_record(project, _spec(project))
    _continuity_project(
        project,
        spec,
        expectations=(ContinuityExpectation(shot_id="shot_a", forbidden_changes=("wardrobe",)),),
    )
    append_record(project, _clip(project, tags=("wardrobe",), source_asset_id="sha256:" + "5" * 64))
    report = continuity_assistant(project, spec.record_id)
    assert report.findings[0].status == "violation"
    assert report.findings[0].violated_forbiddens == ("wardrobe",)


def test_continuity_assistant_empty_when_no_plan(project):
    spec = append_record(project, _spec(project))
    report = continuity_assistant(project, spec.record_id)
    assert report.findings == ()
