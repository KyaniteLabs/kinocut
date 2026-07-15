"""Production cost ledger: append-only writer with explicit unknown cost (#60)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import cost_totals, record_cost_event
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.learning import CostConfidence, CostEvent
from kinocut.projectstore import open_project
from tests.contracts_fixtures import cost_event_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _event(project, **overrides) -> CostEvent:
    return CostEvent(**cost_event_kwargs(project_id=project.project_id, **overrides))


def test_record_cost_event_assigns_canonical_record_id(project):
    stored = record_cost_event(project, _event(project))
    assert stored.record_id == canonical_record_id(_event(project))
    assert stored.record_kind == "cost_event"


def test_record_cost_event_is_append_only(project):
    a = record_cost_event(project, _event(project, source="invoice_a", amount=1.25))
    b = record_cost_event(project, _event(project, source="invoice_b", amount=2.00))
    assert a.record_id != b.record_id
    totals = cost_totals(project)
    assert totals.known_total_usd == pytest.approx(3.25)


def test_unknown_cost_is_explicit_never_zero(project):
    # An unknown cost must carry confidence=unknown and amount=None; it must
    # never be silently counted as a zero known cost.
    record_cost_event(
        project,
        _event(project, amount=None, confidence=CostConfidence.UNKNOWN, source="estimate_pending"),
    )
    totals = cost_totals(project)
    assert totals.known_total_usd == 0.0
    assert totals.unknown_event_count == 1
    assert totals.event_count == 1


def test_cost_totals_group_by_category(project):
    record_cost_event(project, _event(project, category="generation", amount=4.00, source="a"))
    record_cost_event(project, _event(project, category="review", amount=2.50, source="b"))
    record_cost_event(
        project,
        _event(project, category="review", amount=None, confidence=CostConfidence.UNKNOWN, source="c"),
    )
    totals = cost_totals(project)
    assert totals.by_category["generation"] == pytest.approx(4.00)
    assert totals.by_category["review"] == pytest.approx(2.50)
    assert totals.unknown_event_count == 1
    assert totals.known_total_usd == pytest.approx(6.50)


def test_cost_totals_exclude_superseded(project):
    original = record_cost_event(project, _event(project, amount=5.00, source="a"))
    record_cost_event(
        project,
        CostEvent(
            **cost_event_kwargs(
                project_id=project.project_id,
                amount=5.00,
                source="a",
                supersedes=original.record_id,
            )
        ),
    )
    totals = cost_totals(project)
    # The superseded original is excluded; only the superseder counts once.
    assert totals.event_count == 1
    assert totals.known_total_usd == pytest.approx(5.00)
