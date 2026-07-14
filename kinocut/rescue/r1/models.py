"""Pure, separately versioned contracts for rescue extension features."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..models import RescuePlan, Sha256

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_ID_PATTERN = r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$"
_ACTION_ID_PATTERN = r"^[a-z][a-z0-9_]*:[a-z0-9_-]+$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _relative_reference(value: str) -> str:
    if not value or "\x00" in value or Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("path reference must be a non-empty relative path")
    return value


def _hash_payload(model: BaseModel, *, exclude: set[str]) -> Sha256:
    payload = model.model_dump(mode="json", exclude=exclude)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class PolicyPermissions(_FrozenModel):
    """Every permission a feature policy must declare explicitly."""

    timeline: bool = False
    crop: bool = False
    synthesis: bool = False
    network: bool = False
    source_overwrite: bool = False


class PolicyProfile(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: int = Field(ge=1)
    description: str = Field(min_length=1)
    permissions: PolicyPermissions
    gating_checks: tuple[str, ...] = ()


class PolicyRef(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: int = Field(ge=1)


class FeatureIntent(_FrozenModel):
    feature_id: str = Field(pattern=_ID_PATTERN)
    action_ids: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action_ids")
    @classmethod
    def validate_action_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        import re

        if len(values) != len(set(values)):
            raise ValueError("action ids must be unique")
        if any(re.fullmatch(_ACTION_ID_PATTERN, value) is None for value in values):
            raise ValueError("action ids must use the stable action id format")
        return values


class IntentPlanEnvelope(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["intent_plan"] = "intent_plan"
    base_plan: RescuePlan
    policy: PolicyRef
    intent: FeatureIntent
    verifier_ids: tuple[str, ...] = ()
    created_at: datetime
    intent_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @classmethod
    def create(
        cls,
        *,
        base_plan: RescuePlan,
        policy: PolicyRef,
        intent: FeatureIntent,
        verifier_ids: tuple[str, ...] = (),
    ) -> IntentPlanEnvelope:
        if base_plan.plan_sha256 is None:
            raise ValueError("base rescue plan must have plan_sha256")
        draft = cls(
            base_plan=base_plan,
            policy=policy,
            intent=intent,
            verifier_ids=verifier_ids,
            created_at=datetime.now(UTC),
            intent_sha256="sha256:" + "0" * 64,
        )
        return draft.model_copy(update={"intent_sha256": _hash_payload(draft, exclude={"created_at", "intent_sha256"})})


class ExecutorCapability(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(min_length=1)
    hardware: tuple[str, ...]
    determinism_scope: str = Field(min_length=1)
    available: bool = True


class ModelCapability(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(min_length=1)
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    hardware: tuple[str, ...]
    determinism_scope: str = Field(min_length=1)
    available: bool = True


class PreviewPair(_FrozenModel):
    before_path: str
    before_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    after_path: str
    after_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    timestamp_seconds: float = Field(ge=0.0)

    _validate_before = field_validator("before_path")(_relative_reference)
    _validate_after = field_validator("after_path")(_relative_reference)


class PreviewDiff(_FrozenModel):
    schema_version: Literal[1] = 1
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    selected_action_ids: tuple[str, ...]
    previews: tuple[PreviewPair, ...]
    changes: tuple[dict[str, str], ...]
    diff_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


class ApprovalBinding(_FrozenModel):
    schema_version: Literal[1] = 1
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    selected_action_ids: tuple[str, ...]
    preview_diff_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


def model_digest(model: BaseModel, *, exclude: set[str]) -> Sha256:
    """Return the canonical digest used by R1 envelope and approval contracts."""

    return _hash_payload(model, exclude=exclude)
