"""Immutable remote job, receipt, and local-promotion contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from .contracts import (
    JsonObject,
    Money,
    RemoteContractError,
    Sha256,
    _canonical_digest,
    _model_digest,
    _relative_path,
    _FrozenModel,
    redact_credentials,
)

AdapterKind = Literal["render", "delivery", "hosting"]
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9._-]*$"


class ApprovedLocalPlan(_FrozenModel):
    """A local plan already bound to a separate creative approval."""

    schema_version: Literal[1] = 1
    plan: JsonObject
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    creative_intent_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    creative_approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("plan", mode="before")
    @classmethod
    def redact_plan_credentials(cls, value: Any) -> Any:
        return redact_credentials(value)

    @model_validator(mode="after")
    def validate_plan_hash(self) -> ApprovedLocalPlan:
        expected = _canonical_digest(self.plan)
        if self.plan_sha256 != expected:
            raise ValueError("plan_sha256 does not match the approved local plan")
        return self

    @classmethod
    def create(
        cls,
        *,
        plan: Mapping[str, Any],
        creative_intent_sha256: Sha256,
        creative_approval_sha256: Sha256,
    ) -> ApprovedLocalPlan:
        safe_plan = redact_credentials(dict(plan))
        return cls(
            plan=safe_plan,
            plan_sha256=_canonical_digest(safe_plan),
            creative_intent_sha256=creative_intent_sha256,
            creative_approval_sha256=creative_approval_sha256,
        )


class AdapterMapping(_FrozenModel):
    """Provider parameters plus the unchanged approved local plan."""

    approved_plan: JsonObject
    parameters: JsonObject = Field(default_factory=dict)

    @field_validator("approved_plan", "parameters", mode="before")
    @classmethod
    def redact_mapping_credentials(cls, value: Any) -> Any:
        return redact_credentials(value)


class RemoteExecutionSelection(_FrozenModel):
    schema_version: Literal[1] = 1
    scope: Literal["explicit_remote_execution"] = "explicit_remote_execution"
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    kind: AdapterKind
    selected_by: str = Field(min_length=1)
    selected_at: datetime
    selection_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("selected_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("selected_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_selection_hash(self) -> RemoteExecutionSelection:
        if self.selection_sha256 != _model_digest(self, exclude={"selection_sha256"}):
            raise ValueError("selection_sha256 does not match the explicit selection")
        return self

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        kind: AdapterKind,
        selected_by: str,
        selected_at: datetime,
    ) -> RemoteExecutionSelection:
        payload = {
            "schema_version": 1,
            "scope": "explicit_remote_execution",
            "provider": provider,
            "kind": kind,
            "selected_by": selected_by,
            "selected_at": selected_at.isoformat().replace("+00:00", "Z"),
        }
        return cls(
            provider=provider,
            kind=kind,
            selected_by=selected_by,
            selected_at=selected_at,
            selection_sha256=_canonical_digest(payload),
        )


class RemoteJobSpec(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["remote_job"] = "remote_job"
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    adapter_version: str = Field(min_length=1)
    kind: AdapterKind
    local_plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    creative_intent_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    creative_approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    egress_manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    network_approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    remote_selection_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    mapping: AdapterMapping
    job_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_job_hash(self) -> RemoteJobSpec:
        if self.job_sha256 != _model_digest(self, exclude={"job_sha256"}):
            raise ValueError("job_sha256 does not match the remote job")
        return self

    @classmethod
    def create(
        cls,
        *,
        provider: str,
        adapter_version: str,
        kind: AdapterKind,
        local_plan: ApprovedLocalPlan,
        egress_manifest_sha256: Sha256,
        network_approval_sha256: Sha256,
        remote_selection_sha256: Sha256,
        mapping: AdapterMapping,
    ) -> RemoteJobSpec:
        values = {
            "provider": provider,
            "adapter_version": adapter_version,
            "kind": kind,
            "local_plan_sha256": local_plan.plan_sha256,
            "creative_intent_sha256": local_plan.creative_intent_sha256,
            "creative_approval_sha256": local_plan.creative_approval_sha256,
            "egress_manifest_sha256": egress_manifest_sha256,
            "network_approval_sha256": network_approval_sha256,
            "remote_selection_sha256": remote_selection_sha256,
            "mapping": mapping,
        }
        draft = cls.model_construct(**values, schema_version=1, receipt_kind="remote_job")
        return cls(**values, job_sha256=_model_digest(draft, exclude={"job_sha256"}))


class DownloadedArtifact(_FrozenModel):
    provider_artifact_id: str = Field(min_length=1)
    path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)

    _validate_path = field_validator("path")(_relative_path)


class DeletionRecord(_FrozenModel):
    status: Literal["not_requested", "pending", "confirmed", "failed", "unknown"]
    confirmation_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_confirmation(self) -> DeletionRecord:
        if self.status == "confirmed" and self.confirmation_id is None:
            raise ValueError("confirmation_id is required for confirmed deletion")
        return self


class RemoteJobReceipt(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["remote_job_receipt"] = "remote_job_receipt"
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    provider_job_id: str = Field(min_length=1)
    provider_job_version: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    kind: AdapterKind
    job_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    local_plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    creative_intent_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    egress_manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    status: Literal["completed", "failed", "cancelled"]
    actual_cost: Money
    retries: int = Field(ge=0)
    downloads: tuple[DownloadedArtifact, ...]
    deletion: DeletionRecord
    provider_metadata: JsonObject = Field(default_factory=dict)
    receipt_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("provider_metadata", mode="before")
    @classmethod
    def redact_provider_metadata(cls, value: Any) -> Any:
        return redact_credentials(value)

    @field_validator("downloads")
    @classmethod
    def validate_downloads(
        cls, downloads: tuple[DownloadedArtifact, ...]
    ) -> tuple[DownloadedArtifact, ...]:
        paths = tuple(item.path for item in downloads)
        if len(paths) != len(set(paths)):
            raise ValueError("download paths must be unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("downloads must use canonical path order")
        return downloads

    @model_validator(mode="after")
    def validate_receipt_hash(self) -> RemoteJobReceipt:
        if self.receipt_sha256 != _model_digest(self, exclude={"receipt_sha256"}):
            raise ValueError("receipt_sha256 does not match the remote receipt")
        return self

    @classmethod
    def create(
        cls,
        *,
        job: RemoteJobSpec,
        provider_job_id: str,
        provider_job_version: str,
        status: Literal["completed", "failed", "cancelled"],
        actual_cost: Money,
        retries: int,
        downloads: tuple[DownloadedArtifact, ...],
        deletion: DeletionRecord,
        provider_metadata: Mapping[str, Any] | None = None,
    ) -> RemoteJobReceipt:
        values = {
            "provider": job.provider,
            "provider_job_id": provider_job_id,
            "provider_job_version": provider_job_version,
            "adapter_version": job.adapter_version,
            "kind": job.kind,
            "job_sha256": job.job_sha256,
            "local_plan_sha256": job.local_plan_sha256,
            "creative_intent_sha256": job.creative_intent_sha256,
            "egress_manifest_sha256": job.egress_manifest_sha256,
            "status": status,
            "actual_cost": actual_cost,
            "retries": retries,
            "downloads": tuple(sorted(downloads, key=lambda item: item.path)),
            "deletion": deletion,
            "provider_metadata": redact_credentials(dict(provider_metadata or {})),
        }
        draft = cls.model_construct(
            **values, schema_version=1, receipt_kind="remote_job_receipt"
        )
        return cls(**values, receipt_sha256=_model_digest(draft, exclude={"receipt_sha256"}))


class LocalArtifactVerification(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["local_artifact_verification"] = "local_artifact_verification"
    artifact_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    artifact_size_bytes: int = Field(ge=0)
    verifier_id: str = Field(min_length=1)
    verifier_version: str = Field(min_length=1)
    passed: bool
    checks: tuple[str, ...] = Field(min_length=1)
    verified_at: datetime
    verification_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("verified_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("verified_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_verification_hash(self) -> LocalArtifactVerification:
        if self.verification_sha256 != _model_digest(self, exclude={"verification_sha256"}):
            raise ValueError("verification_sha256 does not match local verification")
        return self

    @classmethod
    def create(
        cls,
        *,
        download: DownloadedArtifact,
        verifier_id: str,
        verifier_version: str,
        passed: bool,
        checks: tuple[str, ...],
        verified_at: datetime,
    ) -> LocalArtifactVerification:
        values = {
            "artifact_sha256": download.sha256,
            "artifact_size_bytes": download.size_bytes,
            "verifier_id": verifier_id,
            "verifier_version": verifier_version,
            "passed": passed,
            "checks": checks,
            "verified_at": verified_at,
        }
        draft = cls.model_construct(
            **values, schema_version=1, receipt_kind="local_artifact_verification"
        )
        return cls(
            **values,
            verification_sha256=_model_digest(draft, exclude={"verification_sha256"}),
        )


class PromotionReceipt(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["local_promotion"] = "local_promotion"
    source_path: str
    source_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    destination: str
    local_verification_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    promotion_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    _validate_source = field_validator("source_path")(_relative_path)
    _validate_destination = field_validator("destination")(_relative_path)

    @model_validator(mode="after")
    def validate_promotion_hash(self) -> PromotionReceipt:
        if self.promotion_sha256 != _model_digest(self, exclude={"promotion_sha256"}):
            raise ValueError("promotion_sha256 does not match local promotion")
        return self


def promote_downloaded_artifact(
    download: DownloadedArtifact,
    verification: LocalArtifactVerification,
    *,
    destination: str,
) -> PromotionReceipt:
    """Authorize promotion only after a matching local verification passed."""

    if verification.artifact_sha256 != download.sha256:
        raise RemoteContractError("local verification hash does not match downloaded artifact")
    if verification.artifact_size_bytes != download.size_bytes:
        raise RemoteContractError("local verification size does not match downloaded artifact")
    if not verification.passed:
        raise RemoteContractError("local verification did not pass; promotion is blocked")
    expected_verification = _model_digest(verification, exclude={"verification_sha256"})
    if verification.verification_sha256 != expected_verification:
        raise RemoteContractError("local verification receipt is not hash-valid")
    draft = PromotionReceipt.model_construct(
        source_path=download.path,
        source_sha256=download.sha256,
        destination=destination,
        local_verification_sha256=verification.verification_sha256,
        schema_version=1,
        receipt_kind="local_promotion",
    )
    return PromotionReceipt(
        source_path=download.path,
        source_sha256=download.sha256,
        destination=destination,
        local_verification_sha256=verification.verification_sha256,
        promotion_sha256=_model_digest(draft, exclude={"promotion_sha256"}),
    )
