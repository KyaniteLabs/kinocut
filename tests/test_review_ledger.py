"""Review ledger: timestamped decisions, known-limitation ledger, approval
invalidation, and the fail-closed publish gate (#48, #49, #50, #51)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.review import (
    PublishGateResult,
    evaluate_publish_gate,
    invalidate_approval,
    known_limitations,
    record_approval_state,
    record_known_limitation,
    record_review_decision,
    review_decisions_for_target,
)
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.review import ApprovalState, ApprovalStateValue, KnownLimitation, ReviewDecision
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import approval_state_kwargs, known_limitation_kwargs, review_decision_kwargs

_ASSET = "sha256:" + "a" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _decision(project, **overrides) -> ReviewDecision:
    return ReviewDecision(**review_decision_kwargs(project_id=project.project_id, **overrides))


# --- #48 timestamped review decisions ---


def test_record_review_decision_persists_human_actor_only(project):
    stored = record_review_decision(project, _decision(project))
    assert stored.record_id == canonical_record_id(_decision(project))
    assert stored.actor == "human"
    assert stored.record_kind == "review_decision"


def test_review_decisions_for_target_returns_active_only(project):
    target = "sha256:" + "c" * 64
    original = record_review_decision(project, _decision(project, target_ref=target))
    record_review_decision(
        project,
        _decision(
            project,
            target_ref=target,
            decision="reject",
            supersedes=original.record_id,
            rationale="superseded on re-review",
        ),
    )
    rows = review_decisions_for_target(project, target)
    assert len(rows) == 1
    assert rows[0].decision.value == "reject"


def test_review_decision_rejects_non_human_actor_at_contract(project):
    # The contract pins actor to Literal["human"]; a forged agent actor is rejected.
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ReviewDecision(**review_decision_kwargs(project_id=project.project_id, actor="agent"))


# --- #50 known-limitation ledger ---


def test_record_known_limitation_requires_authorizing_decision(project):
    decision = record_review_decision(project, _decision(project))
    limitation = KnownLimitation(
        **known_limitation_kwargs(project_id=project.project_id, accepted_by_decision_id=decision.record_id)
    )
    stored = record_known_limitation(project, limitation)
    assert stored.record_kind == "known_limitation"
    assert stored.accepted_by_decision_id == decision.record_id


def test_record_known_limitation_rejects_dangling_authorization(project):
    limitation = KnownLimitation(
        **known_limitation_kwargs(
            project_id=project.project_id,
            accepted_by_decision_id="sha256:" + "0" * 64,
        )
    )
    with pytest.raises(MCPVideoError, match="authorizing"):
        record_known_limitation(project, limitation)


def test_known_limitations_query_excludes_superseded(project):
    decision = record_review_decision(project, _decision(project))
    first = record_known_limitation(
        project,
        KnownLimitation(
            **known_limitation_kwargs(project_id=project.project_id, accepted_by_decision_id=decision.record_id)
        ),
    )
    record_known_limitation(
        project,
        KnownLimitation(
            **known_limitation_kwargs(
                project_id=project.project_id,
                accepted_by_decision_id=decision.record_id,
                supersedes=first.record_id,
                summary="revised limitation wording",
            )
        ),
    )
    rows = known_limitations(project)
    assert len(rows) == 1
    assert rows[0].summary == "revised limitation wording"


# --- #51 approval invalidation on dependency change ---


def _approved_state(project, decision_id, fingerprint, **overrides) -> ApprovalState:
    return ApprovalState(
        **approval_state_kwargs(
            project_id=project.project_id,
            candidate_artifact=_ASSET,
            dependency_fingerprint=fingerprint,
            required_artifact_ids=(_ASSET,),
            integrity_results=({"artifact_id": _ASSET, "passed": True},),
            required_human_decisions=(decision_id,),
            state="approved",
            **overrides,
        )
    )


def test_invalidate_approval_appends_superseding_invalidated_state(project):
    decision = record_review_decision(
        project, _decision(project, target_ref=_ASSET, dependency_fingerprint="sha256:" + "b" * 64)
    )
    original = record_approval_state(project, _approved_state(project, decision.record_id, "sha256:" + "b" * 64))
    superseder = invalidate_approval(project, original.record_id, "dependency_fingerprint_changed")
    assert superseder.state is ApprovalStateValue.INVALIDATED
    assert superseder.supersedes == original.record_id
    assert "dependency_fingerprint_changed" in superseder.invalidation_reasons


def test_invalidate_publish_gate_after_invalidation(project):
    fp = "sha256:" + "b" * 64
    decision = record_review_decision(project, _decision(project, target_ref=_ASSET, dependency_fingerprint=fp))
    original = record_approval_state(project, _approved_state(project, decision.record_id, fp))
    assert evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable is True
    invalidate_approval(project, original.record_id, "source_changed")
    result = evaluate_publish_gate(project, _ASSET, blocking_findings=())
    assert result.publishable is False
    assert any("invalidated" in r or "superseded" in r for r in result.reasons)


# --- #49 fail-closed publish gate ---


def test_publish_gate_open_for_clean_approved_candidate(project):
    fp = "sha256:" + "b" * 64
    decision = record_review_decision(project, _decision(project, target_ref=_ASSET, dependency_fingerprint=fp))
    record_approval_state(project, _approved_state(project, decision.record_id, fp))
    result = evaluate_publish_gate(project, _ASSET, blocking_findings=())
    assert isinstance(result, PublishGateResult)
    assert result.publishable is True
    assert result.reasons == ()


def test_publish_gate_fail_closed_with_blocking_finding(project):
    fp = "sha256:" + "b" * 64
    decision = record_review_decision(project, _decision(project, target_ref=_ASSET, dependency_fingerprint=fp))
    record_approval_state(project, _approved_state(project, decision.record_id, fp))
    finding = "sha256:" + "f" * 64
    result = evaluate_publish_gate(project, _ASSET, blocking_findings=(finding,))
    assert result.publishable is False
    assert any("block" in r for r in result.reasons)


def test_publish_gate_fail_closed_with_no_approval_state(project):
    result = evaluate_publish_gate(project, _ASSET, blocking_findings=())
    assert result.publishable is False
    assert any("approval" in r.lower() for r in result.reasons)


# --- #47 review package assembly ---


def test_review_package_assembles_a_publishable_candidate(project):
    from kinocut.aivideo.review import review_package

    fp = "sha256:" + "b" * 64
    decision = record_review_decision(project, _decision(project, target_ref=_ASSET, dependency_fingerprint=fp))
    record_approval_state(project, _approved_state(project, decision.record_id, fp))
    pkg = review_package(project, _ASSET, blocking_findings=())
    assert pkg.candidate_artifact == _ASSET
    assert pkg.publishable is True
    assert decision.record_id in pkg.review_decision_ids
    assert pkg.human_review_required is True


def test_review_package_non_publishable_with_blocking_finding(project):
    from kinocut.aivideo.review import review_package

    fp = "sha256:" + "b" * 64
    decision = record_review_decision(project, _decision(project, target_ref=_ASSET, dependency_fingerprint=fp))
    record_approval_state(project, _approved_state(project, decision.record_id, fp))
    pkg = review_package(project, _ASSET, blocking_findings=("sha256:" + "f" * 64,))
    assert pkg.publishable is False
    assert pkg.publish_gate_reasons


def test_review_package_lists_open_defects(project):
    from kinocut.aivideo.review import review_package
    from kinocut.contracts.defect import DefectFinding
    from tests.contracts_fixtures import defect_kwargs

    append_record(project, DefectFinding(**defect_kwargs(project_id=project.project_id)))
    pkg = review_package(project, _ASSET)
    assert len(pkg.open_defect_ids) == 1
