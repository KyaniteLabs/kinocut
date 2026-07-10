"""Versioned contracts for local, content-preserving video rescue."""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Sha256 = str
_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_REPAIR_ID_PATTERN = r"^[a-z][a-z0-9_]*:[a-z0-9_-]+$"
_CANONICAL_EXCLUDED_FIELDS = frozenset({"plan_sha256", "created_at", "observed_planning_seconds"})


class _StrictModel(BaseModel):
    """Base for artifacts written by schema version 1."""

    model_config = ConfigDict(extra="forbid")


def _relative_reference(value: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("path reference must be a non-empty relative path")
    if Path(value).is_absolute() or PureWindowsPath(value).is_absolute():
        raise ValueError("path reference must be relative")
    return value


class Disposition(StrEnum):
    """Policy decision for a proposed repair."""

    SAFE_REPAIR = "safe_repair"
    RECOMMENDATION = "recommendation"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"


class RepairType(StrEnum):
    """Stable rescue repair catalog."""

    ROTATION = "rotation"
    CONTAINER_TIMESTAMPS = "container_timestamps"
    METADATA = "metadata"
    UNIVERSAL_MP4 = "universal_mp4"
    AUDIO_LOUDNESS = "audio_loudness"
    AUDIO_DENOISE = "audio_denoise"
    EXPOSURE = "exposure"
    WHITE_BALANCE = "white_balance"
    CAPTIONS_TRANSCRIPT = "captions_transcript"
    STABILIZATION = "stabilization"
    REFRAME = "reframe"
    TIMELINE_EDIT = "timeline_edit"
    SYNTHETIC_CONTENT = "synthetic_content"
    CLOUD_PROCESSING = "cloud_processing"


class Metric(_StrictModel):
    """One explicit measurement and its interpretation contract."""

    name: str = Field(min_length=1)
    value: float | int | str | bool | None
    unit: str = Field(min_length=1)
    definition: str = Field(min_length=1)
    available: bool = True


class Finding(_StrictModel):
    """Analyzer evidence before policy assigns an execution disposition."""

    id: str = Field(pattern=_REPAIR_ID_PATTERN)
    type: RepairType
    summary: str = Field(min_length=1)
    evidence: list[Metric] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str = Field(min_length=1)
    parameters: dict[str, int | float | str | bool] = Field(default_factory=dict)
    expected_benefit: str = Field(min_length=1)
    tradeoffs: list[str] = Field(default_factory=list)
    executor: str | None = None
    available: bool = True
    timeline_preserving: bool = True
    contraindications: list[str] = Field(default_factory=list)
    preview_artifacts: list[str] = Field(default_factory=list)

    _validate_preview_paths = field_validator("preview_artifacts")(
        lambda paths: [_relative_reference(path) for path in paths]
    )


class Repair(_StrictModel):
    """Policy-classified action with bounded parameters."""

    id: str = Field(pattern=_REPAIR_ID_PATTERN)
    type: RepairType
    disposition: Disposition
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_rationale: str = Field(min_length=1)
    evidence: list[Metric] = Field(default_factory=list)
    parameters: dict[str, int | float | str | bool] = Field(default_factory=dict)
    expected_benefit: str = Field(min_length=1)
    tradeoffs: list[str] = Field(default_factory=list)
    executor: str | None = None
    promotable: bool
    reason: str | None = None


class PackageIntent(_StrictModel):
    """Artifact the rescue package must produce or explain as unavailable."""

    kind: Literal["master", "sharing_copy", "captions", "transcript", "receipt"]
    required: bool
    status: Literal["available", "unavailable"]
    reason: str | None = None

    @model_validator(mode="after")
    def unavailable_has_reason(self) -> PackageIntent:
        if self.status == "unavailable" and not self.reason:
            raise ValueError("unavailable package intents require a reason")
        return self


class SourceIdentity(_StrictModel):
    """Immutable identity and stream inventory for the source media."""

    path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    streams: list[dict[str, Any]] = Field(default_factory=list)

    _validate_path = field_validator("path")(_relative_reference)


class RescuePolicy(_StrictModel):
    """Policy identity embedded in plans and receipts."""

    id: Literal["local_content_preserving"] = "local_content_preserving"
    version: Literal[1] = 1
    local_only: Literal[True] = True
    timeline_locked: Literal[True] = True


class PreviewArtifact(_StrictModel):
    """Representative read-only diagnosis preview."""

    path: str
    timestamp_seconds: float = Field(ge=0.0)
    timestamp_ratio: float = Field(ge=0.0, le=1.0)
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    _validate_path = field_validator("path")(_relative_reference)


class RescueEstimate(_StrictModel):
    """Deterministic render estimate and the hardware it describes."""

    seconds: float = Field(ge=0.0)
    hardware: dict[str, Any] = Field(default_factory=dict)
    confidence: Literal["low", "medium", "high"]


class RescuePlan(_StrictModel):
    """Version 1 diagnosis and approval artifact."""

    schema_version: Literal[1] = 1
    receipt_kind: Literal["rescue_plan"] = "rescue_plan"
    tool: Literal["video_rescue_plan"] = "video_rescue_plan"
    status: Literal["planned"] = "planned"
    workspace_root: str
    output_root: str
    source: SourceIdentity
    policy: RescuePolicy = Field(default_factory=RescuePolicy)
    findings: list[Finding] = Field(default_factory=list)
    safe_repairs: list[Repair] = Field(default_factory=list)
    recommendations: list[Repair] = Field(default_factory=list)
    unavailable_repairs: list[Repair] = Field(default_factory=list)
    blocked_repairs: list[Repair] = Field(default_factory=list)
    package_intents: list[PackageIntent] = Field(default_factory=list)
    preview_artifacts: list[PreviewArtifact] = Field(default_factory=list)
    estimate: RescueEstimate
    capabilities: dict[str, Any] = Field(default_factory=dict)
    versions: dict[str, str | None] = Field(default_factory=dict)
    created_at: datetime
    observed_planning_seconds: float = Field(ge=0.0)
    plan_sha256: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)

    _validate_workspace_root = field_validator("workspace_root")(_relative_reference)
    _validate_output_root = field_validator("output_root")(_relative_reference)

    @model_validator(mode="after")
    def validate_disposition_buckets(self) -> RescuePlan:
        buckets = (
            ("safe_repairs", self.safe_repairs, Disposition.SAFE_REPAIR),
            ("recommendations", self.recommendations, Disposition.RECOMMENDATION),
            ("unavailable_repairs", self.unavailable_repairs, Disposition.UNAVAILABLE),
            ("blocked_repairs", self.blocked_repairs, Disposition.BLOCKED),
        )
        repairs = [repair for _, bucket, _ in buckets for repair in bucket]
        repair_ids = [repair.id for repair in repairs]
        if len(repair_ids) != len(set(repair_ids)):
            raise ValueError("repair ids must be unique across disposition buckets")
        for name, bucket, expected in buckets:
            if any(repair.disposition is not expected for repair in bucket):
                raise ValueError(f"{name} must contain only {expected.value} repairs")
        finding_ids = [finding.id for finding in self.findings]
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("finding ids must be unique")
        intent_kinds = [intent.kind for intent in self.package_intents]
        if len(intent_kinds) != len(set(intent_kinds)):
            raise ValueError("package intent kinds must be unique")
        return self


class OperationEntry(_StrictModel):
    """One bounded renderer stage recorded in a rescue receipt."""

    id: str = Field(min_length=1)
    repair_id: str | None = Field(default=None, pattern=_REPAIR_ID_PATTERN)
    status: Literal["pending", "completed", "failed", "cancelled", "skipped"]
    input_path: str
    input_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    output_path: str | None = None
    output_sha256: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)
    parameters: dict[str, int | float | str | bool] = Field(default_factory=dict)
    executor: str
    executor_version: str | None = None
    elapsed_ms: int | None = Field(default=None, ge=0)
    error: dict[str, Any] | None = None

    _validate_input_path = field_validator("input_path")(_relative_reference)

    @field_validator("output_path")
    @classmethod
    def validate_optional_output_path(cls, value: str | None) -> str | None:
        return _relative_reference(value) if value is not None else None


class VerificationCheck(_StrictModel):
    """Independent success or failure check with explicit evidence."""

    id: str = Field(min_length=1)
    passed: bool
    gating: bool = True
    message: str = Field(min_length=1)
    metric: Metric | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class PackageArtifact(_StrictModel):
    """One persisted or explicitly unavailable package artifact."""

    kind: Literal["master", "sharing_copy", "captions", "transcript", "receipt", "preview"]
    status: Literal["available", "unavailable"]
    path: str | None = None
    sha256: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)
    size_bytes: int | None = Field(default=None, ge=0)
    reason: str | None = None

    @field_validator("path")
    @classmethod
    def validate_optional_path(cls, value: str | None) -> str | None:
        return _relative_reference(value) if value is not None else None

    @model_validator(mode="after")
    def validate_availability(self) -> PackageArtifact:
        if self.status == "available" and (self.path is None or self.sha256 is None):
            raise ValueError("available package artifacts require path and sha256")
        if self.status == "unavailable" and not self.reason:
            raise ValueError("unavailable package artifacts require a reason")
        return self


class PackageManifest(_StrictModel):
    """Promotion state and artifact inventory."""

    path: str | None = None
    promoted: bool
    artifacts: list[PackageArtifact] = Field(default_factory=list)
    quarantine_path: str | None = None

    @field_validator("path", "quarantine_path")
    @classmethod
    def validate_optional_paths(cls, value: str | None) -> str | None:
        return _relative_reference(value) if value is not None else None


class CleanupState(_StrictModel):
    """Worktree cleanup and retained-resume inventory."""

    work_dir: str
    intermediates: list[str] = Field(default_factory=list)
    cleaned: list[str] = Field(default_factory=list)
    policy: Literal["clean-on-success", "keep-intermediates"] = "clean-on-success"

    _validate_work_dir = field_validator("work_dir")(_relative_reference)
    _validate_intermediates = field_validator("intermediates")(
        lambda paths: [_relative_reference(path) for path in paths]
    )
    _validate_cleaned = field_validator("cleaned")(
        lambda paths: [_relative_reference(path) for path in paths]
    )


class ResumeState(_StrictModel):
    """Whether and where a render resumed."""

    used: bool = False
    receipt_path: str | None = None
    resumed_from: str | None = None

    @field_validator("receipt_path")
    @classmethod
    def validate_optional_receipt_path(cls, value: str | None) -> str | None:
        return _relative_reference(value) if value is not None else None


class PrivacyStatement(_StrictModel):
    """Machine-readable local execution assertion."""

    local_only: Literal[True] = True
    network_used: Literal[False] = False
    source_overwritten: Literal[False] = False


class RescueReceipt(_StrictModel):
    """Version 1 render, verification, and package receipt."""

    schema_version: Literal[1] = 1
    receipt_kind: Literal["rescue"] = "rescue"
    tool: Literal["video_rescue_render"] = "video_rescue_render"
    status: Literal["completed", "failed", "cancelled", "quarantined"]
    workspace_root: str = "."
    output_root: str = "."
    source: SourceIdentity
    plan_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    policy: RescuePolicy = Field(default_factory=RescuePolicy)
    policy_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    approved_repair_ids: list[str] = Field(default_factory=list)
    applied_repair_ids: list[str] = Field(default_factory=list)
    skipped_repair_ids: list[str] = Field(default_factory=list)
    unavailable_repair_ids: list[str] = Field(default_factory=list)
    blocked_repair_ids: list[str] = Field(default_factory=list)
    operations: list[OperationEntry] = Field(default_factory=list)
    measurements: dict[str, list[Metric]] = Field(default_factory=dict)
    verification: list[VerificationCheck] = Field(default_factory=list)
    package: PackageManifest
    progress: dict[str, Any] = Field(default_factory=dict)
    cleanup: CleanupState
    resume: ResumeState = Field(default_factory=ResumeState)
    privacy: PrivacyStatement = Field(default_factory=PrivacyStatement)
    warnings: list[str | dict[str, Any]] = Field(default_factory=list)
    versions: dict[str, str | None] = Field(default_factory=dict)
    created_at: datetime
    receipt_path: str | None = None
    receipt_sha256: Sha256 | None = Field(default=None, pattern=_SHA256_PATTERN)
    error: dict[str, Any] | None = None

    _validate_workspace_root = field_validator("workspace_root")(_relative_reference)
    _validate_output_root = field_validator("output_root")(_relative_reference)

    @field_validator(
        "approved_repair_ids",
        "applied_repair_ids",
        "skipped_repair_ids",
        "unavailable_repair_ids",
        "blocked_repair_ids",
    )
    @classmethod
    def validate_repair_ids(cls, values: list[str]) -> list[str]:
        import re

        if any(re.fullmatch(_REPAIR_ID_PATTERN, value) is None for value in values):
            raise ValueError("receipt repair ids must use the stable repair id format")
        return values

    @field_validator("receipt_path")
    @classmethod
    def validate_optional_receipt_path(cls, value: str | None) -> str | None:
        return _relative_reference(value) if value is not None else None

    @model_validator(mode="after")
    def completed_receipt_is_verified_and_promoted(self) -> RescueReceipt:
        if self.status == "completed":
            if not self.package.promoted:
                raise ValueError("completed rescue receipts require a promoted package")
            if any(check.gating and not check.passed for check in self.verification):
                raise ValueError("completed rescue receipts cannot contain failed gating verification")
        elif self.package.promoted:
            raise ValueError("non-completed rescue receipts cannot promote a package")
        return self


def canonical_payload(
    model: BaseModel,
    excluded: set[str] | frozenset[str] = _CANONICAL_EXCLUDED_FIELDS,
) -> bytes:
    """Serialize action-bearing fields into stable UTF-8 JSON bytes."""

    payload = model.model_dump(mode="json", exclude=set(excluded))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def receipt_integrity_sha256(receipt: RescueReceipt | dict[str, Any]) -> Sha256:
    """Hash a receipt while excluding only its two self-referential digest values."""

    payload = receipt.model_dump(mode="json") if isinstance(receipt, RescueReceipt) else copy.deepcopy(receipt)
    payload["receipt_sha256"] = None
    package = payload.get("package")
    if isinstance(package, dict):
        artifacts = package.get("artifacts")
        if isinstance(artifacts, list):
            for artifact in artifacts:
                if isinstance(artifact, dict) and artifact.get("kind") == "receipt":
                    artifact["sha256"] = None
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()
