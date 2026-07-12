"""Learning records: prompt outcomes, usage, cost, and recipes (design §4.11).

Unknown cost is explicit — ``amount`` is ``None`` with ``unknown`` confidence,
never inferred as zero. Prompts are stored by hash, never as raw text. These
records are the deterministic substrate the learning and cost projections read.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field, model_validator

from kinocut.contracts._common import AssetId, RecordBase, Sha256, ValueObject


class CostConfidence(StrEnum):
    """How firmly a cost amount is known; ``unknown`` means no amount at all."""

    KNOWN = "known"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class ParameterSlot(ValueObject):
    """A typed parameter slot in a workflow recipe template."""

    name: str
    type: str
    required: bool = True


class PromptOutcome(RecordBase):
    """Links a prompt (by hash) to the assets, verdicts, and uses it produced."""

    record_kind: Literal["prompt_outcome"] = "prompt_outcome"

    prompt_hash: Sha256
    generator_model: str
    generator_settings_hash: Sha256 | None = None
    asset_ids: tuple[AssetId, ...] = ()
    verdict_ids: tuple[Sha256, ...] = ()
    defect_ids: tuple[Sha256, ...] = ()
    final_use_event_ids: tuple[Sha256, ...] = ()


class UsageEvent(RecordBase):
    """An approved asset actually used in an output, with its receipt."""

    record_kind: Literal["usage_event"] = "usage_event"

    asset_id: AssetId
    project_beat: str
    output_receipt_id: Sha256
    timestamp: str


class CostEvent(RecordBase):
    """A cost observation; an unknown amount is explicit, never inferred zero."""

    record_kind: Literal["cost_event"] = "cost_event"

    category: str
    quantity: float = Field(ge=0.0)
    unit: str
    currency: str | None = None
    source: str
    amount: float | None = None
    confidence: CostConfidence

    @model_validator(mode="after")
    def _amount_matches_confidence(self) -> CostEvent:
        """Tie amount presence to confidence: unknown ⇔ no amount (design §4.11)."""

        if self.amount is None and self.confidence is not CostConfidence.UNKNOWN:
            raise ValueError("a missing amount requires unknown confidence")
        if self.amount is not None and self.confidence is CostConfidence.UNKNOWN:
            raise ValueError("unknown confidence forbids a concrete amount")
        return self


class WorkflowRecipe(RecordBase):
    """A versioned workflow template with typed slots, policies, and gates."""

    record_kind: Literal["workflow_recipe"] = "workflow_recipe"

    recipe_version: int = Field(ge=1, strict=True)
    template: str
    parameter_slots: tuple[ParameterSlot, ...] = ()
    policies: tuple[str, ...] = ()
    required_checks: tuple[str, ...] = ()
    review_gates: tuple[str, ...] = ()
