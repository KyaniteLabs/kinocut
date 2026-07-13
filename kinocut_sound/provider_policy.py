"""Local-first provider selection with explicit, S2-authorized cloud egress."""

from __future__ import annotations

from itertools import islice
import logging
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel
from kinocut_sound.authorization import AuthorizationContext, AuthorizationError, ConsentLedger
from kinocut_sound.capability import AdapterLocality
from kinocut_sound.limits import (
    MAX_S3_REGISTRY_ADAPTERS,
    MIN_RETENTION_DAYS,
)
from kinocut_sound.registry import Adapter, AdapterRegistry, RegistryError
from kinocut_sound.validation import ISO8601_RE, TERRITORY_RE

logger = logging.getLogger(__name__)


def _error(message: str, code: str) -> RegistryError:
    return RegistryError(message, code=code, suggested_action={"auto_fix": False})


def _codes(values: object) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("provider policy traversal failed")
        raise ValueError("provider policy codes are invalid") from None
    if len(items) > MAX_S3_REGISTRY_ADAPTERS:
        raise ValueError("provider policy codes exceed their ceiling")
    checked = tuple(BoundedCode(value) for value in items)
    if len(set(checked)) != len(checked):
        raise ValueError("provider policy codes must be unique")
    return checked


class ExecutionPolicy(FrozenModel):
    """Explicit local/cloud execution selection policy."""

    allow_cloud: bool = False
    cloud_execution_confirmed: bool = False
    allowed_provider_ids: tuple[str, ...] = ()
    allowed_regions: tuple[str, ...] = ()
    allowed_egress_hosts: tuple[str, ...] = ()
    credential_handles: tuple[str, ...] = ()

    @field_validator(
        "allowed_provider_ids",
        "allowed_regions",
        "allowed_egress_hosts",
        "credential_handles",
        mode="before",
    )
    @classmethod
    def _allowlists(cls, value: object) -> tuple[str, ...]:
        return _codes(value)

    @model_validator(mode="after")
    def _cloud_confirmation_requires_opt_in(self) -> ExecutionPolicy:
        if self.cloud_execution_confirmed and not self.allow_cloud:
            raise ValueError("cloud confirmation requires cloud opt-in")
        return self


class ProviderRequest(FrozenModel):
    """One privacy-safe cloud egress request bound to S2 authorization."""

    egress_host: str = Field(min_length=1)
    credential_handle: str = Field(min_length=1)
    data_classes: tuple[str, ...] = Field(min_length=1)
    retention_days: int = Field(ge=MIN_RETENTION_DAYS)
    territory: str = Field(min_length=1)
    grant_ids: tuple[str, ...] = Field(min_length=1)
    context: AuthorizationContext
    at_iso: str

    @field_validator("egress_host", "credential_handle")
    @classmethod
    def _codes(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("data_classes", "grant_ids", mode="before")
    @classmethod
    def _code_lists(cls, value: object) -> tuple[str, ...]:
        return _codes(value)

    @field_validator("territory")
    @classmethod
    def _territory(cls, value: str) -> str:
        if not TERRITORY_RE.match(value):
            raise ValueError("territory must be bounded")
        return value

    @field_validator("at_iso")
    @classmethod
    def _timestamp(cls, value: str) -> str:
        if not ISO8601_RE.match(value):
            raise ValueError("at_iso must be UTC ISO-8601")
        return value

    @field_validator("retention_days", mode="before")
    @classmethod
    def _strict_retention(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retention_days must be an integer")
        return value


class _AuthorizationLedger(Protocol):
    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        """Authorize exact cloud egress scope."""


def _candidate_ids(values: object) -> tuple[str, ...]:
    try:
        collected = tuple(islice(iter(values), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("provider candidate traversal failed")
        raise _error("provider candidates are invalid", "invalid_provider_candidates") from None
    if not collected or len(collected) > MAX_S3_REGISTRY_ADAPTERS:
        raise _error("provider candidate count is invalid", "invalid_provider_candidates")
    try:
        return _codes(collected)
    except (TypeError, ValueError):
        raise _error("provider candidates are invalid", "invalid_provider_candidates") from None


def _cloud_policy_check(adapter: Adapter, policy: ExecutionPolicy, request: ProviderRequest | None) -> None:
    disclosure = adapter.descriptor.cost_disclosure
    if not policy.allow_cloud or not policy.cloud_execution_confirmed:
        raise _error("cloud execution was not explicitly confirmed", "cloud_execution_denied")
    if request is None:
        raise _error("cloud authorization request is required", "cloud_authorization_required")
    allowed = (
        disclosure is not None
        and disclosure.confirmed
        and disclosure.provider_id in policy.allowed_provider_ids
        and disclosure.region in policy.allowed_regions
        and request.egress_host in policy.allowed_egress_hosts
        and request.credential_handle in policy.credential_handles
        and set(request.data_classes) <= set(disclosure.data_classes)
        and request.retention_days <= disclosure.retention_ceiling_days
        and request.territory == request.context.territory
    )
    if not allowed:
        raise _error("cloud execution policy denied the request", "cloud_execution_denied")


def _authorize_cloud(
    adapter: Adapter,
    ledger: _AuthorizationLedger | None,
    request: ProviderRequest | None,
) -> None:
    if ledger is None or request is None:
        raise _error("cloud authorization request is required", "cloud_authorization_required")
    disclosure = adapter.descriptor.cost_disclosure
    if disclosure is None:
        raise _error("cloud disclosure is missing", "cloud_execution_denied")
    try:
        ledger.authorize_cloud_egress(
            grant_ids=request.grant_ids,
            provider_id=disclosure.provider_id,
            data_classes=request.data_classes,
            territory=request.territory,
            retention_days=request.retention_days,
            at_iso=request.at_iso,
            context=request.context,
        )
    except AuthorizationError:
        logger.warning("S2 cloud egress authorization denied")
        raise _error("cloud authorization was denied", "cloud_authorization_denied") from None


def select_adapter(
    registry: AdapterRegistry,
    candidate_ids: object,
    *,
    kind: str,
    policy: ExecutionPolicy,
    ledger: ConsentLedger | _AuthorizationLedger | None = None,
    request: ProviderRequest | None = None,
) -> Adapter:
    """Select an available local adapter, or an explicitly authorized cloud one."""

    candidates = _candidate_ids(candidate_ids)
    resolved = tuple(registry.resolve(adapter_id, kind=kind) for adapter_id in candidates)
    local = tuple(item for item in resolved if item.descriptor.locality is AdapterLocality.LOCAL)
    if local:
        for adapter in local:
            if registry.probe(adapter.descriptor.adapter_id).available:
                return adapter
        raise _error("local capability is unavailable", "local_capability_unavailable")

    cloud = tuple(item for item in resolved if item.descriptor.locality is AdapterLocality.CLOUD)
    for adapter in cloud:
        _cloud_policy_check(adapter, policy, request)
        if not registry.probe(adapter.descriptor.adapter_id).available:
            continue
        _authorize_cloud(adapter, ledger, request)
        return adapter
    raise _error("cloud capability is unavailable", "adapter_unavailable")
