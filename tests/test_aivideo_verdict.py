"""Governed editorial verdict, defect, and acceptance workflows."""

from __future__ import annotations

import pytest

from kinocut.aivideo.verdict import (
    acceptance_dependency_fingerprint,
    acceptance_eval,
    approved_clips,
    defects_for_asset,
    record_defect,
    record_verdict,
)
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.acceptance import (
    GenerationAcceptanceSpec,
    acceptance_requirement_ids,
)
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.review import ReviewDecision
from kinocut.contracts.verdict import ClipVerdict
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import (
    acceptance_spec_kwargs,
    defect_kwargs,
    review_decision_kwargs,
    verdict_kwargs,
)


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _verdict(project, **overrides) -> ClipVerdict:
    return ClipVerdict(**verdict_kwargs(project_id=project.project_id, **overrides))


def _spec(project, **overrides) -> GenerationAcceptanceSpec:
    if "required_beats" in overrides:
        overrides["semantic_beats"] = tuple(overrides.pop("required_beats"))
    return GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project.project_id, **overrides))


def _defect(project, **overrides) -> DefectFinding:
    return DefectFinding(**defect_kwargs(project_id=project.project_id, **overrides))


def _approved_verdict(project, spec, **overrides) -> ClipVerdict:
    from kinocut.projectstore.artifacts import install_bytes

    asset_hash = overrides.get("asset_hash", "sha256:" + "c" * 64)
    spec_id = canonical_record_id(spec)
    evidence = install_bytes(project, b"motion strip", name="motion-strip.png")
    decision = append_record(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                created_by="human:editor",
                target_ref=asset_hash,
                acceptance_spec_id=spec_id,
                review_role="editor",
                evidence_artifacts=(
                    {
                        "requirement_id": "motion_strip",
                        "artifact_id": evidence.artifact_id,
                    },
                ),
                covered_requirement_ids=acceptance_requirement_ids(spec),
                dependency_fingerprint=acceptance_dependency_fingerprint(asset_hash, spec_id, None),
            )
        ),
    )
    return _verdict(
        project,
        acceptance_spec_id=spec_id,
        created_by="human:editor",
        review_decision_id=decision.record_id,
        **overrides,
    )


def test_rejected_verdict_excluded_from_approved_search(project):
    record_verdict(project, _verdict(project, disposition="rejected"))
    assert approved_clips(project) == []


def test_repairable_verdict_excluded_from_approved_clips(project):
    record_verdict(project, _verdict(project, disposition="repairable"))
    assert approved_clips(project) == []


def test_approved_only_query_is_a_positive_list(project):
    spec = append_record(project, _spec(project))
    approved = record_verdict(project, _approved_verdict(project, spec))
    record_verdict(
        project,
        _verdict(
            project,
            asset_hash="sha256:" + "d" * 64,
            disposition="background_only",
        ),
    )
    assert approved_clips(project) == [approved]


def test_defect_workflow_records_and_queries_exact_asset(project):
    finding = record_defect(project, _defect(project))
    assert defects_for_asset(project, finding.target_id) == [finding]
    assert defects_for_asset(project, "sha256:" + "d" * 64) == []


def test_acceptance_eval_lists_unmet_beats_and_forbidden_defects(project):
    spec = _spec(project, required_beats=["intro"])
    finding = record_defect(project, _defect(project, defect_code="text_drift"))
    verdict = _approved_verdict(
        project,
        spec,
        defect_ids=(finding.record_id,),
    )
    report = acceptance_eval(project, spec=spec, verdicts=[])
    assert set(report.unmet_required) == set(acceptance_requirement_ids(spec))

    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert finding.record_id in report.forbidden_defect_ids
    assert report.accepted is False


def test_approved_verdict_satisfies_requirements_without_blocking_defects(project):
    spec = _spec(project, forbidden_defect_codes=(), severity_thresholds=())
    verdict = _approved_verdict(project, spec)
    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert report.unmet_required == ()
    assert report.accepted is True


def test_threshold_violation_is_reported(project):
    spec = _spec(project, forbidden_defect_codes=())
    finding = record_defect(project, _defect(project, defect_code="identity_drift", severity="medium"))
    verdict = _approved_verdict(
        project,
        spec,
        defect_ids=(finding.record_id,),
    )
    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert finding.record_id in report.threshold_violation_ids
    assert report.accepted is False


def test_unreferenced_same_asset_forbidden_defect_is_reported(project):
    spec = _spec(project, severity_thresholds=())
    finding = record_defect(project, _defect(project, defect_code="text_drift"))
    verdict = _approved_verdict(project, spec, defect_ids=())
    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert finding.record_id in report.forbidden_defect_ids
    assert report.accepted is False


def test_unreferenced_same_asset_threshold_defect_is_reported(project):
    spec = _spec(project, forbidden_defect_codes=())
    finding = record_defect(
        project,
        _defect(project, defect_code="identity_drift", severity="medium"),
    )
    verdict = _approved_verdict(project, spec, defect_ids=())
    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert finding.record_id in report.threshold_violation_ids
    assert report.accepted is False


def test_referenced_foreign_asset_defect_fails_closed(project):
    spec = _spec(project, forbidden_defect_codes=(), severity_thresholds=())
    finding = record_defect(
        project,
        _defect(project, target_id="sha256:" + "d" * 64),
    )
    verdict = _approved_verdict(
        project,
        spec,
        defect_ids=(finding.record_id,),
    )
    report = acceptance_eval(project, spec=spec, verdicts=[verdict])
    assert finding.record_id in report.foreign_defect_ids
    assert report.accepted is False


def test_cross_referenced_defect_is_foreign_even_when_both_assets_are_accepted(project):
    spec = _spec(project, forbidden_defect_codes=(), severity_thresholds=())
    second_asset = "sha256:" + "d" * 64
    finding = record_defect(project, _defect(project, target_id=second_asset))
    first = _approved_verdict(
        project,
        spec,
        defect_ids=(finding.record_id,),
    )
    second = _approved_verdict(
        project,
        spec,
        asset_hash=second_asset,
        defect_ids=(),
    )
    report = acceptance_eval(project, spec=spec, verdicts=[first, second])
    assert finding.record_id in report.foreign_defect_ids
    assert report.accepted is False
