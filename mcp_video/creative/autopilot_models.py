"""Contracts for capability-gated creative autopilot coordination."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from .composition_models import (
    AudioMixTrack,
    CaptionPlan,
    CompositionIntent,
    CompositionPlan,
    CompositionPreview,
    GraphicElement,
    LayoutSpec,
    OutputVariant,
)
from .models import (
    _SHA256_PATTERN,
    _STABLE_ID_PATTERN,
    CreativeModel,
    SelectionEvidence,
    SelectionIntent,
    Sha256,
)

CreativePermission = Literal["timeline", "crop", "synthesis", "asset_sourcing", "network"]


class PlannerCapability(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    version: str = Field(min_length=1)
    proven: bool
    available: bool
    deterministic: bool
    determinism_scope: str = Field(min_length=1)
    required_permissions: tuple[CreativePermission, ...] = ()


class AutopilotPolicy(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    version: int = Field(ge=1)
    allowed_permissions: tuple[CreativePermission, ...] = ()


class AutopilotRequest(CreativeModel):
    id: str = Field(pattern=_STABLE_ID_PATTERN)
    required_capability_ids: tuple[str, ...] = ()
    required_permissions: tuple[CreativePermission, ...] = ()
    selection_intent: SelectionIntent
    selection_evidence: tuple[SelectionEvidence, ...]
    composition_intent: CompositionIntent
    layouts: tuple[LayoutSpec, ...]
    graphics: tuple[GraphicElement, ...] = ()
    audio_tracks: tuple[AudioMixTrack, ...] = ()
    caption_plan: CaptionPlan | None = None
    output_variants: tuple[OutputVariant, ...]


class AutopilotAbstention(CreativeModel):
    code: Literal[
        "capability_missing",
        "capability_unavailable",
        "capability_not_proven",
        "capability_not_deterministic",
        "permission_absent",
        "selection_prerequisite_absent",
        "planner_prerequisite_absent",
    ]
    subject: str = Field(min_length=1)
    message: str = Field(min_length=1)


class AutopilotResult(CreativeModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["creative_autopilot_plan"] = "creative_autopilot_plan"
    request_id: str = Field(pattern=_STABLE_ID_PATTERN)
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    request_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    policy_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    policy_id: str = Field(pattern=_STABLE_ID_PATTERN)
    status: Literal["planned", "abstained"]
    capability_ids: tuple[str, ...]
    capability_bindings: tuple[str, ...]
    plan: CompositionPlan | None
    preview: CompositionPreview | None
    abstentions: tuple[AutopilotAbstention, ...]
    autopilot_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_outcome(self) -> AutopilotResult:
        if self.status == "planned" and (self.plan is None or self.preview is None or self.abstentions):
            raise ValueError("planned autopilot results require plan and preview without abstentions")
        if self.status == "abstained" and (self.plan is not None or self.preview is not None or not self.abstentions):
            raise ValueError("abstained autopilot results require reasons and no plan or preview")
        return self
