"""Tests for the learning records (design §4.11).

``PromptOutcome``, ``UsageEvent``, ``CostEvent``, ``WorkflowRecipe``. Unknown
cost is explicit — ``amount`` is ``None`` with an ``unknown`` confidence, never
inferred as zero. Prompts are stored by hash, never as raw text.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut.contracts._common import RecordBase, canonical_record_id
from kinocut.contracts.learning import (
    CostConfidence,
    CostEvent,
    PromptOutcome,
    UsageEvent,
    WorkflowRecipe,
)
from tests.contracts_fixtures import (
    cost_event_kwargs,
    prompt_outcome_kwargs,
    usage_event_kwargs,
    workflow_recipe_kwargs,
)


def test_prompt_outcome_is_a_record_and_stores_prompt_by_hash():
    outcome = PromptOutcome(**prompt_outcome_kwargs())
    assert isinstance(outcome, RecordBase)
    assert canonical_record_id(outcome).startswith("sha256:")
    assert "prompt" not in PromptOutcome.model_fields
    assert "prompt_hash" in PromptOutcome.model_fields


def test_usage_event_is_a_record():
    event = UsageEvent(**usage_event_kwargs())
    assert isinstance(event, RecordBase)


def test_cost_confidence_is_closed():
    assert {c.value for c in CostConfidence} == {"known", "estimated", "unknown"}


def test_cost_event_known_amount_is_preserved():
    event = CostEvent(**cost_event_kwargs(amount=1.25, confidence="known"))
    assert event.amount == 1.25


def test_cost_event_unknown_amount_is_explicit_none_not_zero():
    event = CostEvent(**cost_event_kwargs(amount=None, confidence="unknown"))
    assert event.amount is None  # never coerced to 0.0


def test_cost_event_known_confidence_requires_amount():
    with pytest.raises(ValidationError):
        CostEvent(**cost_event_kwargs(amount=None, confidence="known"))


def test_cost_event_amount_present_forbids_unknown_confidence():
    with pytest.raises(ValidationError):
        CostEvent(**cost_event_kwargs(amount=1.25, confidence="unknown"))


def test_workflow_recipe_has_typed_parameter_slots():
    recipe = WorkflowRecipe(**workflow_recipe_kwargs())
    assert isinstance(recipe, RecordBase)
    assert recipe.parameter_slots[0].name == "subject"
    assert recipe.parameter_slots[0].type == "string"


def test_workflow_recipe_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        WorkflowRecipe(**workflow_recipe_kwargs(surprise=True))
