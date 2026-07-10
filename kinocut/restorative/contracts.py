"""Fail-closed contracts for evidence-gated restorative features."""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = str
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_ID_PATTERN = r"^[a-z][a-z0-9_.-]*$"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class RestorativeFeature(StrEnum):
    SPEECH_DENOISE = "speech_denoise"
    ADVANCED_COLOR_HDR = "advanced_color_hdr"
    FRAME_REPAIR = "frame_repair"
    BACKGROUND_REPAIR = "background_repair"
    STYLED_CAPTIONS = "styled_captions"


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


class VerificationContract(_FrozenModel):
    id: str = Field(pattern=_ID_PATTERN)
    version: Literal[1] = 1
    feature: RestorativeFeature
    required_gate_ids: tuple[str, ...]


EVIDENCE_CONTRACT_IDS = MappingProxyType({
    feature: f"{feature.value}.evidence.v1" for feature in RestorativeFeature
})
VERIFICATION_CONTRACTS = MappingProxyType(
    {
        RestorativeFeature.SPEECH_DENOISE: VerificationContract(
            id="speech_denoise.verification.v1",
            feature=RestorativeFeature.SPEECH_DENOISE,
            required_gate_ids=(
                "noise_reduced",
                "snr_non_regression",
                "intelligibility_preserved",
                "speech_coverage_preserved",
            ),
        ),
        RestorativeFeature.ADVANCED_COLOR_HDR: VerificationContract(
            id="advanced_color_hdr.verification.v1",
            feature=RestorativeFeature.ADVANCED_COLOR_HDR,
            required_gate_ids=(
                "calibrated_measurement",
                "delivery_color_space",
                "gamut_within_delivery",
                "clipping_stable",
                "neutral_stability",
                "skin_stability",
            ),
        ),
        RestorativeFeature.FRAME_REPAIR: VerificationContract(
            id="frame_repair.verification.v1",
            feature=RestorativeFeature.FRAME_REPAIR,
            required_gate_ids=(
                "temporal_consistency",
                "identity_continuity",
                "object_continuity",
                "source_detail_coverage",
                "no_invented_detail",
                "no_invented_detail_claim",
            ),
        ),
        RestorativeFeature.BACKGROUND_REPAIR: VerificationContract(
            id="background_repair.verification.v1",
            feature=RestorativeFeature.BACKGROUND_REPAIR,
            required_gate_ids=(
                "segmentation_confidence",
                "foreground_coverage_preserved",
                "foreground_object_coverage",
                "edge_stability",
                "no_invented_background",
            ),
        ),
        RestorativeFeature.STYLED_CAPTIONS: VerificationContract(
            id="styled_captions.verification.v1",
            feature=RestorativeFeature.STYLED_CAPTIONS,
            required_gate_ids=(
                "style_approved",
                "readable_contrast",
                "no_caption_clipping",
                "safe_zone_coverage",
                "timing_valid",
                "timing_stable",
            ),
        ),
    }
)
VERIFICATION_CONTRACT_IDS = MappingProxyType(
    {feature: contract.id for feature, contract in VERIFICATION_CONTRACTS.items()}
)


def _relative_local_path(value: str) -> str:
    if (
        not value
        or "\x00" in value
        or "://" in value
        or Path(value).is_absolute()
        or PureWindowsPath(value).is_absolute()
    ):
        raise ValueError("model provenance must use a relative local path")
    return value


def plan_digest(plan: RestorativePlan) -> Sha256:
    payload = plan.model_dump(mode="json", exclude={"plan_sha256"})
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class ModelRequirement(_FrozenModel):
    model_id: str = Field(pattern=_ID_PATTERN)
    version: str = Field(min_length=1)
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)


class ModelProvenance(ModelRequirement):
    origin: Literal["bundled", "local"]
    loaded_from: str
    determinism_scope: str = Field(min_length=1)

    _validate_loaded_from = field_validator("loaded_from")(_relative_local_path)


class RestorativeCapability(_FrozenModel):
    feature: RestorativeFeature
    status: CapabilityStatus
    executor_id: str | None = Field(default=None, pattern=_ID_PATTERN)
    executor_version: str | None = None
    model_provenance: ModelProvenance | None = None
    reason: str | None = None
    substitute_executor_id: Literal[None] = None

    @model_validator(mode="after")
    def validate_status_details(self) -> RestorativeCapability:
        if self.status is CapabilityStatus.AVAILABLE:
            if self.executor_id is None or not self.executor_version:
                raise ValueError("available capability requires executor identity and version")
            if self.reason is not None:
                raise ValueError("available capability cannot carry an abstention reason")
        else:
            if not self.reason:
                raise ValueError("unavailable or unsupported capability requires a reason")
            if self.executor_id is not None or self.executor_version is not None or self.model_provenance is not None:
                raise ValueError("non-available capability cannot expose an executor or model substitute")
        return self


class RestorativePlan(_FrozenModel):
    schema_version: Literal[1] = 1
    feature: RestorativeFeature
    source_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    requested_executor_id: str = Field(pattern=_ID_PATTERN)
    model_requirement: ModelRequirement | None = None
    evidence_contract_id: str = Field(pattern=_ID_PATTERN)
    verification_contract_id: str = Field(pattern=_ID_PATTERN)
    local_only: Literal[True] = True
    network_allowed: Literal[False] = False
    downloads_allowed: Literal[False] = False
    substitution_allowed: Literal[False] = False
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_feature_contracts(self) -> RestorativePlan:
        if self.evidence_contract_id != EVIDENCE_CONTRACT_IDS[self.feature]:
            raise ValueError("plan evidence contract does not match feature")
        if self.verification_contract_id != VERIFICATION_CONTRACT_IDS[self.feature]:
            raise ValueError("plan verification contract does not match feature")
        if self.feature is RestorativeFeature.FRAME_REPAIR and self.model_requirement is None:
            raise ValueError("frame repair requires a model requirement")
        if self.plan_sha256 != plan_digest(self):
            raise ValueError("restorative plan hash does not match canonical content")
        return self

    @classmethod
    def create(
        cls,
        *,
        feature: RestorativeFeature,
        source_sha256: Sha256,
        requested_executor_id: str,
        model_requirement: ModelRequirement | None = None,
    ) -> RestorativePlan:
        payload = {
            "feature": feature,
            "source_sha256": source_sha256,
            "requested_executor_id": requested_executor_id,
            "model_requirement": model_requirement,
            "evidence_contract_id": EVIDENCE_CONTRACT_IDS[feature],
            "verification_contract_id": VERIFICATION_CONTRACT_IDS[feature],
        }
        draft = cls.model_construct(
            **payload,
            plan_sha256="sha256:" + "0" * 64,
        )
        return cls(
            **payload,
            plan_sha256=plan_digest(draft),
        )
