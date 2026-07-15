"""Project learning report: deterministic aggregate over canonical ledgers (#57)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import project_learning_report, record_cost_event, record_prompt_outcome
from kinocut.contracts.learning import CostConfidence
from kinocut.projectstore import open_project
from tests.contracts_fixtures import cost_event_kwargs, prompt_outcome_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def test_learning_report_is_a_deterministic_projection_of_empty_project(project):
    report = project_learning_report(project)
    assert report.verdict_count == 0
    assert report.defect_count == 0
    assert report.prompt_outcome_count == 0
    assert report.cost_event_count == 0
    assert report.usage_event_count == 0
    assert report.recipe_count == 0
    assert report.known_cost_total_usd == 0.0
    assert report.unknown_cost_event_count == 0


def test_learning_report_counts_and_aggregates_each_ledger(project):
    record_prompt_outcome(
        project,
        __import__("kinocut.contracts.learning", fromlist=["PromptOutcome"]).PromptOutcome(
            **prompt_outcome_kwargs(project_id=project.project_id)
        ),
    )
    record_cost_event(
        project,
        __import__("kinocut.contracts.learning", fromlist=["CostEvent"]).CostEvent(
            **cost_event_kwargs(project_id=project.project_id, amount=3.00, source="a")
        ),
    )
    record_cost_event(
        project,
        __import__("kinocut.contracts.learning", fromlist=["CostEvent"]).CostEvent(
            **cost_event_kwargs(
                project_id=project.project_id,
                amount=None,
                confidence=CostConfidence.UNKNOWN,
                source="b",
            )
        ),
    )
    report = project_learning_report(project)
    assert report.prompt_outcome_count == 1
    assert report.cost_event_count == 2
    assert report.known_cost_total_usd == pytest.approx(3.00)
    assert report.unknown_cost_event_count == 1


def test_learning_report_is_idempotent_and_read_only(project):
    first = project_learning_report(project)
    second = project_learning_report(project)
    assert first == second
    # A report never mutates the store: no new records appear after building it.
    from kinocut.projectstore import read_records

    before = sum(len(read_records(project, k)) for k in ("prompt_outcome", "cost_event"))
    project_learning_report(project)
    after = sum(len(read_records(project, k)) for k in ("prompt_outcome", "cost_event"))
    assert before == after
