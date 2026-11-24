"""Publish-gate identity and defect regressions (roast audit D-01, T-04).

``video_review_decision`` filled in ``created_by="human:review"`` for any MCP
caller, and the publish gate trusts a ``human`` label, so an agent could mint
the human approval the gate exists to require. Separately, the gate only
blocked on findings the caller chose to list; the project's own open defects
were looked up afterwards, for display only.
"""

from __future__ import annotations

import pytest

from kinocut.aivideo.release_surfaces import _run_review_decision
from kinocut.aivideo.review import (
    evaluate_publish_gate,
    record_approval_state,
    record_review_decision,
    review_package,
)
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.review import ApprovalState, ReviewDecision
from kinocut.errors import MCPVideoError
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import (
    approval_state_kwargs,
    defect_kwargs,
    review_decision_kwargs,
)

_ASSET = "sha256:" + "a" * 64
_FINGERPRINT = "sha256:" + "b" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _approved(project):
    decision = record_review_decision(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id, target_ref=_ASSET, dependency_fingerprint=_FINGERPRINT
            )
        ),
    )
    record_approval_state(
        project,
        ApprovalState(
            **approval_state_kwargs(
                project_id=project.project_id,
                candidate_artifact=_ASSET,
                dependency_fingerprint=_FINGERPRINT,
                required_artifact_ids=(_ASSET,),
                integrity_results=({"artifact_id": _ASSET, "passed": True},),
                required_human_decisions=(decision.record_id,),
                state="approved",
            )
        ),
    )
    return decision


# --- D-01: an agent-reachable surface cannot mint human approval -----------------


def test_agent_surface_refuses_a_decision_labelled_human(project) -> None:
    payload = review_decision_kwargs(project_id=project.project_id, created_by="human:review")
    with pytest.raises(MCPVideoError) as refused:
        _run_review_decision(str(project.root), payload)
    assert refused.value.code == "human_decision_requires_human_channel"


def test_agent_decision_is_recorded_under_its_own_label(project) -> None:
    payload = review_decision_kwargs(project_id=project.project_id, created_by="agent:orchestrator")
    result = _run_review_decision(str(project.root), payload)
    assert result["review_decision"]["created_by"] == "agent:orchestrator"


def test_created_by_is_never_defaulted_to_human(project) -> None:
    payload = review_decision_kwargs(project_id=project.project_id)
    del payload["created_by"]
    with pytest.raises(MCPVideoError) as invalid:
        _run_review_decision(str(project.root), payload, human_channel=True)
    assert invalid.value.code == "invalid_review_decision"


def test_the_cli_channel_records_human_decisions(project) -> None:
    payload = review_decision_kwargs(project_id=project.project_id, created_by="human:editor")
    result = _run_review_decision(str(project.root), payload, human_channel=True)
    assert result["review_decision"]["created_by"] == "human:editor"


def test_an_agent_decision_does_not_satisfy_the_publish_gate(project) -> None:
    decision = record_review_decision(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id, target_ref=_ASSET, dependency_fingerprint=_FINGERPRINT
            )
        ),
    )
    # Re-label the required decision as agent-made: the same record id, no human provenance.
    agent_decision = record_review_decision(
        project,
        ReviewDecision(
            **review_decision_kwargs(
                project_id=project.project_id,
                target_ref=_ASSET,
                dependency_fingerprint=_FINGERPRINT,
                created_by="agent:orchestrator",
            )
        ),
    )
    assert decision.record_id != agent_decision.record_id
    record_approval_state(
        project,
        ApprovalState(
            **approval_state_kwargs(
                project_id=project.project_id,
                candidate_artifact=_ASSET,
                dependency_fingerprint=_FINGERPRINT,
                required_artifact_ids=(_ASSET,),
                integrity_results=({"artifact_id": _ASSET, "passed": True},),
                required_human_decisions=(agent_decision.record_id,),
                state="approved",
            )
        ),
    )
    assert evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable is False


# --- T-04: the project's own open defects block publishing ------------------------


def test_open_defects_block_the_gate_even_when_the_caller_lists_none(project) -> None:
    _approved(project)
    assert evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable is True

    open_defect = append_record(
        project, DefectFinding(**defect_kwargs(project_id=project.project_id, status="suspected"))
    )

    result = evaluate_publish_gate(project, _ASSET, blocking_findings=())
    assert result.publishable is False
    assert any("unresolved finding" in reason for reason in result.reasons)

    package = review_package(project, _ASSET)
    assert package.publishable is False
    assert open_defect.record_id in package.open_defect_ids


def test_resolved_defects_do_not_block(project) -> None:
    decision = _approved(project)
    append_record(
        project,
        DefectFinding(
            **defect_kwargs(project_id=project.project_id, status="resolved", human_decision_id=decision.record_id)
        ),
    )
    assert evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable is True
