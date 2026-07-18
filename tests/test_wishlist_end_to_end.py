"""End-to-end operator-path verification: drive the REAL record pipeline
(spec -> asset -> verdict -> decision -> register_clip -> outcome -> cost ->
beat-map -> continuity-plan -> review -> approval -> defect) through every
shipped wishlist engine, asserting each consumes validated records correctly.

This replaces the synthetic ``append_record(ClipRecord(...))`` shortcut with the
real ref-validating pipeline (``register_clip`` validates verdict/decision/asset
existence) so the engines are exercised against records a real editor flow would
produce.
"""

from __future__ import annotations

import pytest

from kinocut.aivideo.editorial import (
    beat_maps_for_spec,
    continuity_assistant,
    continuity_plans_for_spec,
    coverage_report,
    record_beat_map,
    record_continuity_plan,
)
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
from kinocut.contracts.editorial import BeatRequirement, ContinuityExpectation
from kinocut.contracts.learning import CostEvent, PromptOutcome, WorkflowRecipe
from kinocut.contracts.registry import ClipRecord
from kinocut.contracts.review import ApprovalState, KnownLimitation, ReviewDecision
from kinocut.contracts.verdict import ClipVerdict, Disposition
from kinocut.projectstore import append_record, open_project
from kinocut.registry import duplicate_clip_groups, register_clip
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
from tests.registry_fixtures import clip_record_kwargs

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


def _seed_decision(project, target_ref):
    return append_record(
        project, ReviewDecision(**review_decision_kwargs(project_id=project.project_id, target_ref=target_ref))
    )


def _register_clip(project, *, asset_id, source_asset_id, verdict_id, decision_id, tags):
    return register_clip(
        project,
        ClipRecord(
            **clip_record_kwargs(
                project_id=project.project_id,
                asset_id=asset_id,
                source_asset_id=source_asset_id,
                verdict_id=verdict_id,
                review_decision_id=decision_id,
                tags=tags,
            )
        ),
    )


def test_real_pipeline_drives_every_wishlist_engine(project):
    spec = _seed_spec(project)
    _seed_asset(project, _ASSET)
    _seed_asset(project, _ASSET_B)
    verdict_ok = _seed_verdict(project, _ASSET, spec.record_id, Disposition.APPROVED)
    verdict_bad = _seed_verdict(project, _ASSET_B, spec.record_id, Disposition.REJECTED)
    decision = _seed_decision(project, _ASSET)

    # Real register_clip (validates verdict/decision/asset refs).
    clip_a = _register_clip(
        project,
        asset_id=_ASSET,
        source_asset_id=_ASSET,
        verdict_id=verdict_ok.record_id,
        decision_id=decision.record_id,
        tags=("product",),
    )
    clip_b = _register_clip(
        project,
        asset_id=_ASSET,
        source_asset_id=_ASSET_B,
        verdict_id=verdict_ok.record_id,
        decision_id=decision.record_id,
        tags=("product", "logo"),
    )
    assert clip_a.record_id != clip_b.record_id

    # #39 duplicate detection over the REAL clip registry.
    dups = duplicate_clip_groups(project)
    assert len(dups.exact) == 1 and dups.exact[0].clip_count == 2

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

    # #42 beat map + #43 coverage against the real approved clips' tags.
    beat_map = record_beat_map(
        project,
        _beat_map(project, spec.record_id),
    )
    assert beat_maps_for_spec(project, spec.record_id) == [beat_map]
    coverage = coverage_report(project, spec.record_id)
    product = next(b for b in coverage.beats if b.beat_id == "product")
    assert product.covered is True  # "product" is in the registered clips' tags

    # #45 continuity plan + #19 continuity assistant over the real clip tags.
    plan = record_continuity_plan(project, _continuity_plan(project, spec.record_id))
    assert continuity_plans_for_spec(project, spec.record_id) == [plan]
    continuity = continuity_assistant(project, spec.record_id)
    assert continuity.findings  # the plan has expectations resolved against real tags

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


def _beat_map(project, spec_id):
    from kinocut.contracts.editorial import BeatMap

    return BeatMap(
        **{
            "project_id": project.project_id,
            "created_by": "human",
            "acceptance_spec_id": spec_id,
            "beats": (
                BeatRequirement(beat_id="product", label="Product beat", required_subjects=("product",)),
                BeatRequirement(beat_id="logo", label="Logo beat", required_subjects=("logo",)),
            ),
        }
    )


def _continuity_plan(project, spec_id):
    from kinocut.contracts.editorial import ContinuityPlan

    return ContinuityPlan(
        **{
            "project_id": project.project_id,
            "created_by": "human",
            "acceptance_spec_id": spec_id,
            "expectations": (ContinuityExpectation(shot_id="shot_a", expected_subjects=("product",)),),
        }
    )


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
