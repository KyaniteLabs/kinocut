"""Pure, immutable contracts for explicit remote egress."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PureWindowsPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..errors import MCPVideoError

Sha256 = str
JsonObject = dict[str, Any]

_SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
_PROVIDER_PATTERN = r"^[a-z][a-z0-9._-]*$"
_REDACTED = "[REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(?:authorization|api[_-]?key|access[_-]?key|private[_-]?key|secret|password|passwd|credential|cookie|token)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"\bBearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\b(?:gh[pousr]_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"^[a-z][a-z0-9+.-]*://[^/@\s]+:[^/@\s]+@", re.IGNORECASE),
)


class RemoteContractError(MCPVideoError, ValueError):
    """A fail-closed remote boundary validation error."""

    def __init__(self, message: str, *, code: str = "invalid_remote_contract") -> None:
        super().__init__(message, error_type="validation_error", code=code)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _canonical_digest(value: Any) -> Sha256:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _model_digest(model: BaseModel, *, exclude: set[str]) -> Sha256:
    return _canonical_digest(model.model_dump(mode="json", exclude=exclude))


def _relative_path(value: str) -> str:
    path = Path(value)
    if (
        not value
        or "\x00" in value
        or path.is_absolute()
        or PureWindowsPath(value).is_absolute()
        or any(part == ".." for part in path.parts)
    ):
        raise ValueError("path must be a non-empty relative path without traversal")
    return value


def redact_credentials(value: Any) -> Any:
    """Return a JSON-shaped copy with credential keys and values redacted."""

    if isinstance(value, Mapping):
        return {
            str(key): _REDACTED if _SENSITIVE_KEY.search(str(key)) else redact_credentials(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(redact_credentials(item) for item in value)
    if isinstance(value, list):
        return [redact_credentials(item) for item in value]
    if isinstance(value, str) and any(pattern.search(value) for pattern in _SENSITIVE_VALUE_PATTERNS):
        return _REDACTED
    return value


class Money(_FrozenModel):
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class ProviderLocation(_FrozenModel):
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    region_known: bool
    region: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_region_state(self) -> ProviderLocation:
        if self.region_known and self.region is None:
            raise ValueError("region is required when region_known is true")
        if not self.region_known and self.region is not None:
            raise ValueError("region must be omitted when region_known is false")
        return self


class RetentionPolicy(_FrozenModel):
    mode: Literal["delete_after_download", "fixed_days", "provider_default"]
    maximum_days: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_maximum_days(self) -> RetentionPolicy:
        if self.mode in {"delete_after_download", "fixed_days"} and self.maximum_days is None:
            raise ValueError(f"maximum_days is required for {self.mode}")
        if self.mode == "provider_default" and self.maximum_days is not None:
            raise ValueError("maximum_days must be omitted for provider_default")
        return self


class EgressFile(_FrozenModel):
    path: str
    sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    size_bytes: int = Field(ge=0)
    media_type: str = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)

    _validate_path = field_validator("path")(_relative_path)

    @field_validator("metadata", mode="before")
    @classmethod
    def redact_metadata(cls, value: Any) -> Any:
        return redact_credentials(value)


class EgressManifest(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["egress_manifest"] = "egress_manifest"
    files: tuple[EgressFile, ...] = Field(min_length=1)
    metadata: JsonObject = Field(default_factory=dict)
    location: ProviderLocation
    retention: RetentionPolicy
    estimated_cost: Money
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("metadata", mode="before")
    @classmethod
    def redact_metadata(cls, value: Any) -> Any:
        return redact_credentials(value)

    @field_validator("files")
    @classmethod
    def validate_files(cls, files: tuple[EgressFile, ...]) -> tuple[EgressFile, ...]:
        paths = tuple(item.path for item in files)
        if len(paths) != len(set(paths)):
            raise ValueError("egress file paths must be unique")
        if paths != tuple(sorted(paths)):
            raise ValueError("egress files must use canonical path order")
        return files

    @model_validator(mode="after")
    def validate_manifest_hash(self) -> EgressManifest:
        expected = _model_digest(self, exclude={"manifest_sha256"})
        if self.manifest_sha256 != expected:
            raise ValueError("manifest_sha256 does not match the manifest")
        return self

    @classmethod
    def create(
        cls,
        *,
        files: tuple[EgressFile, ...],
        metadata: Mapping[str, Any],
        location: ProviderLocation,
        retention: RetentionPolicy,
        estimated_cost: Money,
    ) -> EgressManifest:
        ordered_files = tuple(sorted(files, key=lambda item: item.path))
        paths = tuple(item.path for item in ordered_files)
        if len(paths) != len(set(paths)):
            raise RemoteContractError("egress file paths must be unique")
        payload = {
            "schema_version": 1,
            "receipt_kind": "egress_manifest",
            "files": [item.model_dump(mode="json") for item in ordered_files],
            "metadata": redact_credentials(dict(metadata)),
            "location": location.model_dump(mode="json"),
            "retention": retention.model_dump(mode="json"),
            "estimated_cost": estimated_cost.model_dump(mode="json"),
        }
        return cls(
            files=ordered_files,
            metadata=payload["metadata"],
            location=location,
            retention=retention,
            estimated_cost=estimated_cost,
            manifest_sha256=_canonical_digest(payload),
        )


class NetworkApproval(_FrozenModel):
    schema_version: Literal[1] = 1
    receipt_kind: Literal["network_approval"] = "network_approval"
    scope: Literal["network_egress"] = "network_egress"
    manifest_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)
    provider: str = Field(pattern=_PROVIDER_PATTERN)
    approved_by: str = Field(min_length=1)
    approved_at: datetime
    approval_sha256: Sha256 = Field(pattern=_SHA256_PATTERN)

    @field_validator("approved_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("approved_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_approval_hash(self) -> NetworkApproval:
        expected = _model_digest(self, exclude={"approval_sha256"})
        if self.approval_sha256 != expected:
            raise ValueError("approval_sha256 does not match the approval")
        return self

    @classmethod
    def create(
        cls,
        *,
        manifest: EgressManifest,
        approved_by: str,
        approved_at: datetime,
    ) -> NetworkApproval:
        payload = {
            "schema_version": 1,
            "receipt_kind": "network_approval",
            "scope": "network_egress",
            "manifest_sha256": manifest.manifest_sha256,
            "provider": manifest.location.provider,
            "approved_by": approved_by,
            "approved_at": approved_at.isoformat().replace("+00:00", "Z"),
        }
        return cls(
            manifest_sha256=manifest.manifest_sha256,
            provider=manifest.location.provider,
            approved_by=approved_by,
            approved_at=approved_at,
            approval_sha256=_canonical_digest(payload),
        )


def assert_network_approval(manifest: EgressManifest, approval: NetworkApproval) -> None:
    """Fail unless a separate approval binds this exact manifest and provider."""

    if approval.manifest_sha256 != manifest.manifest_sha256:
        raise RemoteContractError("network approval does not match the egress manifest")
    if approval.provider != manifest.location.provider:
        raise RemoteContractError("network approval provider does not match the egress manifest")


def plan_egress(
    *,
    files: list[dict[str, Any]],
    metadata: dict[str, Any],
    provider: str,
    region_known: bool,
    region: str | None = None,
    retention: dict[str, Any],
    estimated_cost: dict[str, Any],
) -> dict[str, Any]:
    """Build a deterministic JSON-compatible egress manifest without I/O."""

    manifest = EgressManifest.create(
        files=tuple(EgressFile.model_validate(item) for item in files),
        metadata=metadata,
        location=ProviderLocation(provider=provider, region_known=region_known, region=region),
        retention=RetentionPolicy.model_validate(retention),
        estimated_cost=Money.model_validate(estimated_cost),
    )
    return manifest.model_dump(mode="json")


def approve_egress(
    manifest: Mapping[str, Any],
    *,
    approved_by: str,
    approved_at: str,
) -> dict[str, Any]:
    """Create a separate JSON-compatible approval for an exact manifest."""

    parsed_manifest = EgressManifest.model_validate(manifest)
    parsed_time = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    approval = NetworkApproval.create(
        manifest=parsed_manifest,
        approved_by=approved_by,
        approved_at=parsed_time,
    )
    return approval.model_dump(mode="json")


def validate_egress_approval(manifest: Mapping[str, Any], approval: Mapping[str, Any]) -> Literal[True]:
    """Validate JSON-compatible egress and approval documents."""

    assert_network_approval(
        EgressManifest.model_validate(manifest),
        NetworkApproval.model_validate(approval),
    )
    return True
