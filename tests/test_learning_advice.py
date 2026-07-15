"""Regeneration advice and defect-to-prompt feedback (#44, #58)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import defect_prompt_feedback, regeneration_advice
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.learning import PromptOutcome
from kinocut.contracts.verdict import ClipVerdict
from kinocut.projectstore import append_record, open_project
from tests.contracts_fixtures import defect_kwargs, prompt_outcome_kwargs, verdict_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _verdict(project, disposition: str) -> ClipVerdict:
    return append_record(
        project,
        ClipVerdict(**verdict_kwargs(project_id=project.project_id, disposition=disposition)),
    )


def _outcome(project, *, verdict_ids=(), defect_ids=(), **overrides) -> PromptOutcome:
    return append_record(
        project,
        PromptOutcome(
            **prompt_outcome_kwargs(
                project_id=project.project_id, verdict_ids=verdict_ids, defect_ids=defect_ids, **overrides
            )
        ),
    )


# --- #44 regeneration advice ---


def test_regeneration_advice_recommends_for_rejected_verdict_with_no_prior_approved(project):
    verdict = _verdict(project, "rejected")
    advice = regeneration_advice(project, verdict.record_id)
    assert advice is not None
    assert advice.recommend_regenerate is True
    assert advice.basis == "rule_based"  # never mistaken for model output
    assert advice.prior_approved_outcome is False
    assert advice.cost_estimate_known is False  # no cost events -> unknown, never inferred zero


def test_regeneration_advice_returns_none_for_unknown_verdict(project):
    assert regeneration_advice(project, "sha256:" + "0" * 64) is None


def test_regeneration_advice_does_not_recommend_for_approved_verdict(project):
    verdict = _verdict(project, "approved")
    advice = regeneration_advice(project, verdict.record_id)
    assert advice.recommend_regenerate is False


def test_regeneration_advice_labels_cost_known_when_cost_events_exist(project):
    from kinocut.aivideo.learning import record_cost_event
    from kinocut.contracts.learning import CostEvent
    from tests.contracts_fixtures import cost_event_kwargs

    verdict = _verdict(project, "rejected")
    record_cost_event(
        project,
        CostEvent(**cost_event_kwargs(project_id=project.project_id, amount=2.50, source="inv")),
    )
    advice = regeneration_advice(project, verdict.record_id)
    assert advice.cost_estimate_known is True


# --- #58 defect-to-prompt feedback ---


def test_defect_prompt_feedback_aggregates_codes_per_prompt(project):
    defect = append_record(
        project, DefectFinding(**defect_kwargs(project_id=project.project_id, defect_code="text_drift"))
    )
    _outcome(project, defect_ids=(defect.record_id,))
    feedback = defect_prompt_feedback(project)
    assert len(feedback) == 1
    assert "text_drift" in feedback[0].defect_codes
    assert feedback[0].defect_count == 1


def test_defect_prompt_feedback_empty_when_no_defects_linked(project):
    _outcome(project)  # outcome with a verdict link but no defects
    assert defect_prompt_feedback(project) == []
