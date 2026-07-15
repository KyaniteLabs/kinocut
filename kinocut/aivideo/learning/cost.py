"""Production cost ledger: append-only writer with explicit unknown cost (#60).

Cost is never inferred as zero: an unknown amount carries
:class:`~kinocut.contracts.learning.CostConfidence.UNKNOWN` and a ``None``
amount (enforced on the contract). Derived totals sum only known USD amounts
and count unknown events separately.
"""

from __future__ import annotations


from pydantic import Field

from kinocut.contracts._common import ValueObject
from kinocut.contracts.learning import CostConfidence, CostEvent
from kinocut.projectstore import Project, append_record, read_records

_USD = "USD"


class CostTotals(ValueObject):
    """Derived, read-only projection of the cost ledger; never a source of truth."""

    event_count: int = Field(ge=0)
    known_event_count: int = Field(ge=0)
    unknown_event_count: int = Field(ge=0)
    known_total_usd: float = Field(ge=0.0)
    by_category: dict[str, float] = Field(default_factory=dict)


def _active_cost_events(project: Project) -> list[CostEvent]:
    rows = [item for item in read_records(project, "cost_event") if type(item) is CostEvent]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def record_cost_event(project: Project, event: CostEvent) -> CostEvent:
    """Append one cost event. Each event is distinct; pass ``supersedes`` to correct."""

    appended = append_record(project, event)
    return appended  # type: ignore[return-value]


def cost_totals(project: Project) -> CostTotals:
    """Sum known USD amounts by category and count unknown-cost events."""

    events = _active_cost_events(project)
    by_category: dict[str, float] = {}
    known_total = 0.0
    known_count = 0
    unknown_count = 0
    for event in events:
        if event.confidence is CostConfidence.UNKNOWN or event.amount is None:
            unknown_count += 1
            continue
        # Only like-currency (USD) amounts are summed directly; non-USD known
        # amounts are counted as known but excluded from the USD total to avoid
        # mixing units. This keeps the projection honest about its assumptions.
        if event.currency == _USD:
            known_total += event.amount
            by_category[event.category] = by_category.get(event.category, 0.0) + event.amount
        known_count += 1
    return CostTotals(
        event_count=len(events),
        known_event_count=known_count,
        unknown_event_count=unknown_count,
        known_total_usd=round(known_total, 6),
        by_category={k: round(v, 6) for k, v in sorted(by_category.items())},
    )


__all__ = ["CostTotals", "cost_totals", "record_cost_event"]
