"""Workflow recipe capture: versioned template registry (#59).

A :class:`~kinocut.contracts.learning.WorkflowRecipe` records a versioned
template with typed parameter slots, policies, required checks, and review
gates. Recording is idempotent by canonical digest (template + version + slots
+ policies + checks + gates), so the same recipe never duplicates.
"""

from __future__ import annotations

from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.learning import WorkflowRecipe
from kinocut.projectstore import Project, append_record, read_records


def _active_recipes(project: Project) -> list[WorkflowRecipe]:
    rows = [item for item in read_records(project, "workflow_recipe") if type(item) is WorkflowRecipe]
    superseded = {item.supersedes for item in rows if item.supersedes is not None}
    return [item for item in rows if item.record_id not in superseded]


def record_workflow_recipe(project: Project, recipe: WorkflowRecipe) -> WorkflowRecipe:
    """Persist one recipe, idempotent by canonical digest."""

    digest = canonical_record_id(recipe)
    for existing in _active_recipes(project):
        if existing.record_id == digest:
            return existing
    return append_record(project, recipe)  # type: ignore[return-value]


def recipes_for_template(project: Project, template: str) -> list[WorkflowRecipe]:
    """Return active recipe versions for ``template``."""

    return [item for item in _active_recipes(project) if item.template == template]


__all__ = ["recipes_for_template", "record_workflow_recipe"]
