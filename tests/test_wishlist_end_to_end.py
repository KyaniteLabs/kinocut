"""Exercise the wishlist learning and review engines with validated project records."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import (
    cost_totals,
    defect_prompt_feedback,
    prompt_outcomes_for_asset,
    project_learning_report,
    record_cost_event,
    record_prompt_outcome,
    record_workflow_recipe,
    recipes_for_template,
    regeneration_advice,
)
from kinocut.aivideo.review import (
    evaluate_publish_gate,
    invalidate_approval,
    known_limitations,
    record_approval_state,
    record_known_limitation,
    record_review_decision,
    review_decisions_for_target,
    review_package,
)
from kinocut.contracts.acceptance import GenerationAcceptanceSpec
from kinocut.contracts.asset import AssetRecord
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.learning import CostEvent, PromptOutcome, WorkflowRecipe
from kinocut.contracts.review import ApprovalState, KnownLimitation, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import (
    acceptance_spec_kwargs,
    approval_state_kwargs,
    asset_record_kwargs,
    cost_event_kwargs,
    defect_kwargs,
    known_limitation_kwargs,
    prompt_outcome_kwargs,
    review_decision_kwargs,
    verdict_kwargs,
    workflow_recipe_kwargs,
)

_ASSET = "sha256:" + "d" * 64
_ASSET_B = "sha256:" + "e" * 64
_FP = "sha256:" + "b" * 64


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _seed_spec(project):
    return append_record(project, GenerationAcceptanceSpec(**acceptance_spec_kwargs(project_id=project.project_id)))


def _seed_asset(project, asset_id):
    return append_record(
        project,
        AssetRecord(
            **asset_record_kwargs(
                project_id=project.project_id,
                asset_id=asset_id,
                original_location=f"inputs/{asset_id[:12]}.mp4",
                lineage=None,
            )
        ),
    )


def _seed_verdict(project, asset_hash, spec_id, disposition):
    return append_record(
        project,
        ClipVerdict(
            **verdict_kwargs(
                project_id=project.project_id,
                asset_hash=asset_hash,
                disposition=disposition,
                acceptance_spec_id=spec_id,
            )
        ),
    )


def test_real_pipeline_drives_learning_and_review_engines(project):
    spec = _seed_spec(project)
    _seed_asset(project, _ASSET)
    _seed_asset(project, _ASSET_B)
    verdict_ok = _seed_verdict(project, _ASSET, spec.record_id, Disposition.APPROVED)
    verdict_bad = _seed_verdict(project, _ASSET_B, spec.record_id, Disposition.REJECTED)

    # #40 prompt-outcome + #60 cost, written through the real writers.
    outcome = record_prompt_outcome(
        project,
        PromptOutcome(
            **prompt_outcome_kwargs(
                project_id=project.project_id, asset_ids=(_ASSET,), verdict_ids=(verdict_ok.record_id,)
            )
        ),
    )
    assert prompt_outcomes_for_asset(project, _ASSET) == [outcome]
    record_cost_event(project, CostEvent(**cost_event_kwargs(project_id=project.project_id, amount=4.25, source="inv")))
    totals = cost_totals(project)
    assert totals.known_total_usd == pytest.approx(4.25)

    # #57 learning report aggregates the real records.
    report = project_learning_report(project)
    assert report.verdict_count == 2 and report.prompt_outcome_count == 1 and report.cost_event_count == 1

    # #48 review decisions + #49 publish gate + #47 review package.
    review_decision = record_review_decision(
        project,
        ReviewDecision(
            **review_decision_kwargs(project_id=project.project_id, target_ref=_ASSET, dependency_fingerprint=_FP)
        ),
    )
    assert review_decision.record_id in {d.record_id for d in review_decisions_for_target(project, _ASSET)}
    approval = record_approval_state(project, _approval(project, review_decision.record_id))
    gate = evaluate_publish_gate(project, _ASSET, blocking_findings=())
    assert gate.publishable is True
    pkg = review_package(project, _ASSET, blocking_findings=())
    assert pkg.publishable is True and review_decision.record_id in set(pkg.review_decision_ids)

    # #51 invalidation flips the gate closed.
    invalidated = invalidate_approval(project, approval.record_id, "source_changed")
    assert invalidated.state.value == "invalidated"
    assert evaluate_publish_gate(project, _ASSET, blocking_findings=()).publishable is False

    # #50 known limitation authorized by the real review decision.
    limitation = record_known_limitation(
        project,
        KnownLimitation(
            **known_limitation_kwargs(
                project_id=project.project_id,
                accepted_by_decision_id=review_decision.record_id,
                summary="accepted flicker",
            )
        ),
    )
    assert limitation.record_id in {lim.record_id for lim in known_limitations(project)}

    # #58 defect-to-prompt feedback: real defect linked to the real prompt outcome.
    defect = append_record(project, DefectFinding(**defect_kwargs(project_id=project.project_id, target_id=_ASSET)))
    record_prompt_outcome(
        project,
        PromptOutcome(
            **prompt_outcome_kwargs(
                project_id=project.project_id,
                asset_ids=(_ASSET,),
                verdict_ids=(verdict_ok.record_id,),
                defect_ids=(defect.record_id,),
            )
        ),
    )
    feedback = defect_prompt_feedback(project)
    assert feedback and feedback[0].defect_count >= 1

    # #44 regeneration advice over the real rejected verdict.
    advice = regeneration_advice(project, verdict_bad.record_id)
    assert advice is not None and advice.recommend_regenerate is True
    assert regeneration_advice(project, verdict_ok.record_id).recommend_regenerate is False

    # #59 workflow recipe through the real writer.
    recipe = record_workflow_recipe(project, WorkflowRecipe(**workflow_recipe_kwargs(project_id=project.project_id)))
    assert recipes_for_template(project, recipe.template) == [recipe]


def _approval(project, decision_id):
    return ApprovalState(
        **approval_state_kwargs(
            project_id=project.project_id,
            candidate_artifact=_ASSET,
            dependency_fingerprint=_FP,
            required_artifact_ids=(_ASSET,),
            integrity_results=({"artifact_id": _ASSET, "passed": True},),
            required_human_decisions=(decision_id,),
            state="approved",
        )
    )
