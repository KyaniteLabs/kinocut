"""Workflow recipe capture: versioned template registry (#59)."""

from __future__ import annotations

import pytest

from kinocut.aivideo.learning import recipes_for_template, record_workflow_recipe
from kinocut.contracts._common import canonical_record_id
from kinocut.contracts.learning import WorkflowRecipe
from kinocut.projectstore import open_project
from tests.contracts_fixtures import workflow_recipe_kwargs


@pytest.fixture
def project(tmp_path):
    return open_project(tmp_path / "project")


def _recipe(project, **overrides) -> WorkflowRecipe:
    return WorkflowRecipe(**workflow_recipe_kwargs(project_id=project.project_id, **overrides))


def test_record_workflow_recipe_assigns_canonical_id(project):
    recipe = _recipe(project)
    stored = record_workflow_recipe(project, recipe)
    assert stored.record_id == canonical_record_id(recipe)
    assert stored.record_kind == "workflow_recipe"


def test_record_workflow_recipe_is_idempotent_by_template_and_version(project):
    recipe = _recipe(project)
    first = record_workflow_recipe(project, recipe)
    second = record_workflow_recipe(project, recipe)
    assert first.record_id == second.record_id


def test_distinct_recipe_versions_are_separate_records(project):
    v1 = record_workflow_recipe(project, _recipe(project, recipe_version=1))
    v2 = record_workflow_recipe(project, _recipe(project, recipe_version=2))
    assert v1.record_id != v2.record_id


def test_recipes_for_template_returns_active_versions(project):
    record_workflow_recipe(project, _recipe(project, template="hero_shot", recipe_version=1))
    v2 = record_workflow_recipe(project, _recipe(project, template="hero_shot", recipe_version=2))
    record_workflow_recipe(project, _recipe(project, template="intro_card", recipe_version=1))
    rows = recipes_for_template(project, "hero_shot")
    assert {r.recipe_version for r in rows} == {1, 2}
    assert v2.record_id in {r.record_id for r in rows}


def test_recipes_for_template_excludes_superseded(project):
    first = record_workflow_recipe(project, _recipe(project, template="hero_shot", recipe_version=1))
    record_workflow_recipe(
        project,
        _recipe(project, template="hero_shot", recipe_version=1, supersedes=first.record_id),
    )
    rows = recipes_for_template(project, "hero_shot")
    assert len(rows) == 1
    assert rows[0].supersedes == first.record_id
