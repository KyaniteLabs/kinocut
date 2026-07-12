"""Hostile regressions for durable store identity and human acceptance proof."""

from __future__ import annotations

import json
import shutil

import pytest

from kinocut.contracts.verdict import ClipVerdict
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project, read_records
from tests.contracts_fixtures import verdict_kwargs


def _rejected(project_id: str, **overrides: object) -> ClipVerdict:
    values = verdict_kwargs(
        project_id=project_id,
        disposition="rejected",
        review_decision_id=None,
    )
    values.update(overrides)
    return ClipVerdict(**values)


def test_project_identity_is_random_stable_and_not_the_directory_name(tmp_path):
    first = open_project(tmp_path / "same" / "project")
    second = open_project(tmp_path / "other" / "project")

    assert first.project_id.startswith("project:")
    assert len(first.project_id) == len("project:") + 64
    assert first.project_id != first.root.name
    assert first.project_id != second.project_id
    assert open_project(first.root).project_id == first.project_id

    metadata = json.loads((first.root / ".kinocut" / "project.json").read_text())
    assert metadata == {"project_id": first.project_id, "schema_version": 1}


def test_same_basename_stores_reject_each_others_records(tmp_path):
    first = open_project(tmp_path / "one" / "project")
    second = open_project(tmp_path / "two" / "project")
    foreign = _rejected(first.project_id)

    with pytest.raises(MCPVideoError) as excinfo:
        append_record(second, foreign)

    assert excinfo.value.code == "invalid_record"
    assert read_records(second, "clip_verdict") == []


def test_read_rejects_record_from_copied_mismatched_store(tmp_path):
    first = open_project(tmp_path / "one" / "project")
    second = open_project(tmp_path / "two" / "project")
    append_record(first, _rejected(first.project_id))

    source = first.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    target = second.root / ".kinocut" / "records" / "clip_verdict.jsonl"
    shutil.copyfile(source, target)

    with pytest.raises(MCPVideoError) as excinfo:
        read_records(second, "clip_verdict")
    assert excinfo.value.code == "invalid_record"


def test_open_rejects_initialized_legacy_store_without_identity(tmp_path):
    root = tmp_path / "legacy"
    records = root / ".kinocut" / "records"
    records.mkdir(parents=True)
    (records / "clip_verdict.jsonl").write_text("{}\n", encoding="utf-8")

    with pytest.raises(MCPVideoError) as excinfo:
        open_project(root)
    assert excinfo.value.code == "invalid_record"


def test_open_rejects_metadata_changed_after_handle_was_opened(tmp_path):
    project = open_project(tmp_path / "project")
    metadata_path = project.root / ".kinocut" / "project.json"
    metadata_path.write_text(
        json.dumps({"schema_version": 1, "project_id": "project:" + "f" * 64}),
        encoding="utf-8",
    )

    with pytest.raises(MCPVideoError) as excinfo:
        append_record(project, _rejected(project.project_id))
    assert excinfo.value.code == "invalid_record"


def test_project_metadata_schema_version_is_strict_integer(tmp_path):
    project = open_project(tmp_path / "project")
    metadata_path = project.root / ".kinocut" / "project.json"
    metadata_path.write_text(
        json.dumps({"schema_version": 1.0, "project_id": project.project_id}),
        encoding="utf-8",
    )

    with pytest.raises(MCPVideoError) as excinfo:
        open_project(project.root)
    assert excinfo.value.code == "invalid_record"


def _acceptance_bundle(tmp_path, *, empty: bool = False):
    from kinocut.contracts.acceptance import GenerationAcceptanceSpec
    from kinocut.contracts.asset import AssetRecord
    from kinocut.projectstore.artifacts import install_bytes
    from tests.contracts_fixtures import acceptance_spec_kwargs, asset_record_kwargs

    project = open_project(tmp_path / "governed")
    asset = append_record(
        project,
        AssetRecord(
            **asset_record_kwargs(
                project_id=project.project_id,
                original_location="inputs/candidate.mp4",
                preflight_artifact_id=None,
            )
        ),
    )
    overrides = {
        "project_id": project.project_id,
        "forbidden_defect_codes": (),
        "severity_thresholds": (),
    }
    if empty:
        overrides.update(
            required_subjects=(),
            required_actions=(),
            semantic_beats=(),
            exact_text_hash=None,
            declared_text_region=None,
            required_logos=(),
            required_evidence_artifacts=(),
            required_review_roles=(),
        )
    spec = append_record(project, GenerationAcceptanceSpec(**acceptance_spec_kwargs(**overrides)))
    evidence = install_bytes(project, b"motion strip proof", name="motion-strip.png")
    return project, asset, spec, evidence


def _approval(
    project,
    asset,
    spec,
    evidence,
    *,
    covered=None,
    approved_range=None,
    **overrides,
):
    from kinocut.aivideo.verdict import acceptance_dependency_fingerprint
    from kinocut.contracts.acceptance import acceptance_requirement_ids
    from kinocut.contracts.review import ReviewDecision
    from tests.contracts_fixtures import review_decision_kwargs

    values = review_decision_kwargs(
        project_id=project.project_id,
        created_by="human:editor",
        decision="approve",
        target_ref=asset.asset_id,
        target_range=approved_range,
        acceptance_spec_id=spec.record_id,
        dependency_fingerprint=acceptance_dependency_fingerprint(asset.asset_id, spec.record_id, approved_range),
        review_role="editor",
        evidence_artifacts=({"requirement_id": "motion_strip", "artifact_id": evidence.artifact_id},),
        covered_requirement_ids=(tuple(acceptance_requirement_ids(spec)) if covered is None else tuple(covered)),
    )
    values.update(overrides)
    return append_record(project, ReviewDecision(**values))


def _approved_payload(project, asset, spec, decision, **overrides):
    values = verdict_kwargs(
        project_id=project.project_id,
        created_by="human:editor",
        asset_hash=asset.asset_id,
        acceptance_spec_id=spec.record_id,
        disposition="approved",
        defect_ids=(),
        review_decision_id=decision.record_id if decision is not None else None,
    )
    values.update(overrides)
    return values


def test_public_approved_verdict_requires_active_exact_human_decision(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, asset, spec, _ = _acceptance_bundle(tmp_path)
    payload = _approved_payload(project, asset, spec, None)

    with pytest.raises(MCPVideoError) as excinfo:
        run_wave3_operation("verdict", project_dir=str(project.root), verdict=payload)
    assert excinfo.value.code == "wave3_approval_invalid"


@pytest.mark.parametrize(
    "decision_overrides",
    (
        {"created_by": "agent:reviewer"},
        {"decision": "reject"},
        {"target_ref": "sha256:" + "f" * 64},
        {"acceptance_spec_id": "sha256:" + "f" * 64},
        {"review_role": "producer"},
        {"dependency_fingerprint": "sha256:" + "f" * 64},
        {"target_range": (0.0, 1.0)},
        {
            "evidence_artifacts": (
                {
                    "requirement_id": "unrequested_evidence",
                    "artifact_id": "sha256:" + "f" * 64,
                },
            )
        },
        {"covered_requirement_ids": ("subject:sha256:" + "f" * 64,)},
    ),
)
def test_public_approved_verdict_rejects_inexact_human_evidence(tmp_path, decision_overrides):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, asset, spec, evidence = _acceptance_bundle(tmp_path)
    decision = _approval(project, asset, spec, evidence, **decision_overrides)
    with pytest.raises(MCPVideoError) as excinfo:
        run_wave3_operation(
            "verdict",
            project_dir=str(project.root),
            verdict=_approved_payload(project, asset, spec, decision),
        )
    assert excinfo.value.code == "wave3_approval_invalid"


def test_acceptance_requires_human_approval_even_for_empty_content_spec(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, _, spec, _ = _acceptance_bundle(tmp_path, empty=True)
    result = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=[],
    )

    assert result["report"]["accepted"] is False
    assert result["report"]["missing_approval"] is True


def test_acceptance_requires_requirement_level_role_and_evidence_coverage(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, asset, spec, evidence = _acceptance_bundle(tmp_path)
    decision = _approval(project, asset, spec, evidence, covered=())
    verdict_result = run_wave3_operation(
        "verdict",
        project_dir=str(project.root),
        verdict=_approved_payload(project, asset, spec, decision),
    )
    report = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=[verdict_result["verdict"]["record_id"]],
    )["report"]

    assert report["accepted"] is False
    assert report["unmet_required"]
    assert report["missing_review_roles"] == []
    assert report["missing_evidence_artifacts"] == []


def test_valid_exact_human_evidence_accepts_and_tampered_artifact_fails(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, asset, spec, evidence = _acceptance_bundle(tmp_path)
    decision = _approval(project, asset, spec, evidence)
    verdict_result = run_wave3_operation(
        "verdict",
        project_dir=str(project.root),
        verdict=_approved_payload(project, asset, spec, decision),
    )
    arguments = {
        "project_dir": str(project.root),
        "acceptance_spec_id": spec.record_id,
        "verdict_ids": [verdict_result["verdict"]["record_id"]],
    }
    assert run_wave3_operation("acceptance_eval", **arguments)["report"]["accepted"] is True

    artifact_dir = project.root / ".kinocut" / "artifacts" / "sha256" / evidence.artifact_id.removeprefix("sha256:")
    next(artifact_dir.iterdir()).write_bytes(b"tampered")
    report = run_wave3_operation("acceptance_eval", **arguments)["report"]
    assert report["accepted"] is False
    assert report["invalid_evidence_artifact_ids"] == [evidence.artifact_id]


def test_approved_with_trim_requires_exact_human_range_binding(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation

    project, asset, spec, evidence = _acceptance_bundle(tmp_path)
    approved_range = (0.25, 1.5)
    decision = _approval(
        project,
        asset,
        spec,
        evidence,
        approved_range=approved_range,
    )
    payload = _approved_payload(
        project,
        asset,
        spec,
        decision,
        disposition="approved_with_trim",
        approved_range=approved_range,
    )
    stored = run_wave3_operation("verdict", project_dir=str(project.root), verdict=payload)["verdict"]
    report = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=[stored["record_id"]],
    )["report"]
    assert report["accepted"] is True

    wrong_decision = _approval(
        project,
        asset,
        spec,
        evidence,
        approved_range=(0.5, 1.5),
        rationale="different trim range",
    )
    with pytest.raises(MCPVideoError) as excinfo:
        run_wave3_operation(
            "verdict",
            project_dir=str(project.root),
            verdict=_approved_payload(
                project,
                asset,
                spec,
                wrong_decision,
                disposition="approved_with_trim",
                approved_range=approved_range,
            ),
        )
    assert excinfo.value.code == "wave3_approval_invalid"


def test_superseded_decision_and_conflicting_active_verdict_fail_closed(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.contracts.review import ReviewDecision

    project, asset, spec, evidence = _acceptance_bundle(tmp_path)
    decision = _approval(project, asset, spec, evidence)
    replacement = ReviewDecision(
        **{
            **decision.model_dump(mode="json", exclude={"record_id"}),
            "decision": "reject",
            "rationale": "approval withdrawn",
            "supersedes": decision.record_id,
            "evidence_artifacts": (),
            "covered_requirement_ids": (),
        }
    )
    append_record(project, replacement)
    with pytest.raises(MCPVideoError) as superseded:
        run_wave3_operation(
            "verdict",
            project_dir=str(project.root),
            verdict=_approved_payload(project, asset, spec, decision),
        )
    assert superseded.value.code == "wave3_approval_invalid"

    active = _approval(project, asset, spec, evidence, rationale="fresh approval")
    approved = run_wave3_operation(
        "verdict",
        project_dir=str(project.root),
        verdict=_approved_payload(project, asset, spec, active),
    )["verdict"]
    rejected = append_record(
        project,
        _rejected(
            project.project_id,
            asset_hash=asset.asset_id,
            acceptance_spec_id=spec.record_id,
            created_by="human:editor",
        ),
    )
    report = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=[approved["record_id"], rejected.record_id],
    )["report"]
    assert report["accepted"] is False
    assert set(report["conflicting_verdict_ids"]) == {approved["record_id"], rejected.record_id}


def test_conflicting_evidence_bindings_fail_closed(tmp_path):
    from kinocut.aivideo.wave3_surfaces import run_wave3_operation
    from kinocut.projectstore.artifacts import install_bytes

    project, asset, spec, first_evidence = _acceptance_bundle(tmp_path)
    second_evidence = install_bytes(project, b"different proof", name="other.png")
    first_decision = _approval(project, asset, spec, first_evidence)
    second_decision = _approval(
        project,
        asset,
        spec,
        second_evidence,
        rationale="second reviewer evidence",
    )
    verdicts = []
    for decision in (first_decision, second_decision):
        verdicts.append(
            run_wave3_operation(
                "verdict",
                project_dir=str(project.root),
                verdict=_approved_payload(project, asset, spec, decision),
            )["verdict"]["record_id"]
        )
    report = run_wave3_operation(
        "acceptance_eval",
        project_dir=str(project.root),
        acceptance_spec_id=spec.record_id,
        verdict_ids=verdicts,
    )["report"]
    assert report["accepted"] is False
    assert report["conflicting_evidence_requirements"] == ["motion_strip"]
