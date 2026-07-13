"""Capability & adapter descriptor contracts.

The capability contract exposes typed adapter descriptors and a fail-closed
``CapabilityResult``. Adapter locality (local vs cloud) is closed; a cloud
adapter must disclose cost/retention/region before any call. Required
capabilities that probe unavailable yield a validation error for a demanded
render — never a silent fallback to remote. The static code-owned registry
itself is the S3 leaf; here we own the typed contract shape.

Design references (sonic-world design):
* Core contracts §"Capability & Adapter Registry".
* Provider & Model Capability Behavior.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound.defaults import DEFAULT_ADAPTER_TIMEOUT_SECONDS
from kinocut_sound.limits import (
    MAX_ADAPTER_TIMEOUT_SECONDS,
    MIN_COST_USD,
    MIN_RETENTION_DAYS,
    MIN_TIME_SECONDS,
)
from kinocut_sound.validation import ADAPTER_KINDS, ADVISORY_RE, REGION_RE


class AdapterLocality(StrEnum):
    """Where an adapter runs — local-first; cloud is opt-in."""

    LOCAL = "local"
    CLOUD = "cloud"


class CostDisclosure(FrozenModel):
    """Pre-call disclosure for a cloud adapter: provider, region, retention, cost.

    A cloud egress never occurs without a confirmed disclosure on record. The
    fields here are bounded codes and numbers so a host path, secret, or
    unbounded prose cannot ride in.
    """

    provider_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    data_classes: tuple[str, ...] = Field(min_length=1)
    retention_ceiling_days: int = Field(ge=MIN_RETENTION_DAYS)
    estimated_cost_usd_per_call: float = Field(ge=MIN_COST_USD)
    confirmed: bool

    @field_validator("provider_id")
    @classmethod
    def _provider_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("region")
    @classmethod
    def _region_bounded(cls, value: str) -> str:
        if not REGION_RE.match(value):
            raise ValueError("region must be a bounded code (no spaces or paths)")
        return value

    @field_validator("data_classes")
    @classmethod
    def _data_classes_bounded_and_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for code in value:
            BoundedCode(code)
        if len(set(value)) != len(value):
            raise ValueError("data_classes must be unique")
        return value

    @field_validator("retention_ceiling_days", mode="before")
    @classmethod
    def _retention_strict_int(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retention_ceiling_days must be a non-negative integer")
        return value

    @field_validator("estimated_cost_usd_per_call")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("estimated_cost_usd_per_call must not be a boolean")
        return value


class AdapterDescriptor(FrozenModel):
    """Static, code-owned descriptor for one adapter."""

    adapter_id: str = Field(min_length=1)
    kind: str
    locality: AdapterLocality
    provider_class: str = Field(min_length=1)
    cost_disclosure: CostDisclosure | None = None
    timeout_seconds: float = Field(
        default=DEFAULT_ADAPTER_TIMEOUT_SECONDS,
        gt=MIN_TIME_SECONDS,
        le=MAX_ADAPTER_TIMEOUT_SECONDS,
    )

    @field_validator("adapter_id", "provider_class")
    @classmethod
    def _ids_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("kind")
    @classmethod
    def _kind_is_closed(cls, value: str) -> str:
        if value not in ADAPTER_KINDS:
            raise ValueError(f"kind must be one of {sorted(ADAPTER_KINDS)}")
        return value

    @field_validator("timeout_seconds")
    @classmethod
    def _reject_bool_numerics(cls, value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("timeout_seconds must not be a boolean")
        return value

    @model_validator(mode="after")
    def _cloud_requires_disclosure(self) -> AdapterDescriptor:
        if self.locality is AdapterLocality.LOCAL and self.cost_disclosure is not None:
            raise ValueError("local locality must not carry cloud disclosure")
        if self.locality is AdapterLocality.CLOUD and self.cost_disclosure is None:
            raise ValueError("cloud locality requires cost_disclosure")
        return self


class CapabilityResult(FrozenModel):
    """Fail-closed capability probe result for one adapter."""

    adapter_id: str = Field(min_length=1)
    available: bool
    reason_code: str | None = None
    remediation: str | None = None

    @field_validator("adapter_id")
    @classmethod
    def _adapter_id_bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("reason_code")
    @classmethod
    def _reason_code_bounded(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else value

    @field_validator("remediation")
    @classmethod
    def _remediation_advisory(cls, value: str | None) -> str | None:
        if value is not None and not ADVISORY_RE.match(value):
            raise ValueError("remediation must be short and free of paths, URLs, or metacharacters")
        return value

    @model_validator(mode="after")
    def _availability_coherence(self) -> CapabilityResult:
        if self.available:
            if self.reason_code is not None or self.remediation is not None:
                raise ValueError("available result must carry no reason_code or remediation")
        else:
            if self.reason_code is None or self.remediation is None:
                raise ValueError("unavailable result requires reason_code and remediation")
        return self
