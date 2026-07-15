"""Project learning report: deterministic aggregate over canonical ledgers (#57).

A read-only projection over the verdict, defect, prompt-outcome, usage, cost,
recipe, and (when present) review ledgers. It is never an independent source of
truth — drop the report and it rebuilds identically from the records.
"""

from __future__ import annotations

from pydantic import Field

from kinocut.aivideo.learning.cost import cost_totals
from kinocut.contracts._common import ValueObject
from kinocut.contracts.defect import DefectFinding
from kinocut.contracts.learning import PromptOutcome, UsageEvent, WorkflowRecipe
from kinocut.contracts.verdict import ClipVerdict
from kinocut.projectstore import Project, read_records


class LearningReport(ValueObject):
    """Deterministic project learning projection."""

    verdict_count: int = Field(ge=0)
    defect_count: int = Field(ge=0)
    prompt_outcome_count: int = Field(ge=0)
    cost_event_count: int = Field(ge=0)
    usage_event_count: int = Field(ge=0)
    recipe_count: int = Field(ge=0)
    known_cost_total_usd: float = Field(ge=0.0)
    unknown_cost_event_count: int = Field(ge=0)
    cost_by_category: dict[str, float] = Field(default_factory=dict)


def _active(project: Project, kind: str, model: type) -> list[object]:
    rows = [item for item in read_records(project, kind) if type(item) is model]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def project_learning_report(project: Project) -> LearningReport:
    """Build the learning report from current canonical records."""

    totals = cost_totals(project)
    return LearningReport(
        verdict_count=len(_active(project, "clip_verdict", ClipVerdict)),
        defect_count=len(_active(project, "defect_finding", DefectFinding)),
        prompt_outcome_count=len(_active(project, "prompt_outcome", PromptOutcome)),
        cost_event_count=totals.event_count,
        usage_event_count=len(_active(project, "usage_event", UsageEvent)),
        recipe_count=len(_active(project, "workflow_recipe", WorkflowRecipe)),
        known_cost_total_usd=totals.known_total_usd,
        unknown_cost_event_count=totals.unknown_event_count,
        cost_by_category=dict(totals.by_category),
    )


__all__ = ["LearningReport", "project_learning_report"]
