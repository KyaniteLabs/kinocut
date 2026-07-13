"""Local-first provider selection with exact S2-authorized cloud routes."""

from __future__ import annotations

from dataclasses import dataclass
import hmac
from itertools import islice
import logging
import secrets
from typing import Protocol, TypeVar

from pydantic import Field, PrivateAttr, StrictBool, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256, canonical_digest
from kinocut_sound.authorization import AuthorizationContext, AuthorizationError, ConsentLedger
from kinocut_sound.capability import AdapterDescriptor, AdapterLocality, CapabilityResult, CostDisclosure
from kinocut_sound.defaults import (
    DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_MAX_CONCURRENCY,
    DEFAULT_PROVIDER_MAX_DURATION_SECONDS,
    DEFAULT_PROVIDER_MAX_INPUT_BYTES,
    DEFAULT_PROVIDER_MAX_OUTPUT_BYTES,
    DEFAULT_PROVIDER_MAX_RETRIES,
    DEFAULT_PROVIDER_RATE_LIMIT_PER_MINUTE,
    DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS,
    DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
)
from kinocut_sound.limits import (
    MAX_PROVIDER_CONCURRENCY,
    MAX_PROVIDER_CONNECT_TIMEOUT_SECONDS,
    MAX_PROVIDER_DURATION_SECONDS,
    MAX_PROVIDER_INPUT_BYTES,
    MAX_PROVIDER_OUTPUT_BYTES,
    MAX_PROVIDER_RATE_LIMIT_PER_MINUTE,
    MAX_PROVIDER_READ_TIMEOUT_SECONDS,
    MAX_PROVIDER_RETRIES,
    MAX_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    MAX_S3_REGISTRY_ADAPTERS,
    MIN_COST_USD,
    MIN_PROVIDER_BYTES,
    MIN_PROVIDER_CONCURRENCY,
    MIN_PROVIDER_RATE_LIMIT_PER_MINUTE,
    MIN_PROVIDER_RETRIES,
    MIN_RETENTION_DAYS,
    MIN_TIME_SECONDS,
)
from kinocut_sound.registry import Adapter, AdapterRegistry, RegistryError, ResolvedAdapter
from kinocut_sound.validation import ISO8601_RE, TERRITORY_RE

logger = logging.getLogger(__name__)

_ModelT = TypeVar("_ModelT", bound=FrozenModel)
_APPROVAL_SIGNING_KEY = secrets.token_bytes(32)


def _error(message: str, code: str) -> RegistryError:
    return RegistryError(message, code=code, suggested_action={"auto_fix": False})


def _codes(values: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("provider policy traversal failed")
        raise ValueError("provider policy codes are invalid") from None
    if len(items) > MAX_S3_REGISTRY_ADAPTERS or (not items and not allow_empty):
        raise ValueError("provider policy codes exceed their ceiling")
    checked = tuple(BoundedCode(value) for value in items)
    if len(set(checked)) != len(checked):
        raise ValueError("provider policy codes must be unique")
    return tuple(sorted(checked))


def _plain_fields(value: object, model_type: type[_ModelT]) -> dict[str, object]:
    if not isinstance(value, model_type):
        raise TypeError("contract instance type mismatch")
    return {name: getattr(value, name) for name in model_type.model_fields}


class ProviderExecutionLimits(FrozenModel):
    """Typed network, resource, and retry limits for one provider request."""

    connect_timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_CONNECT_TIMEOUT_SECONDS,
        gt=MIN_TIME_SECONDS,
        le=MAX_PROVIDER_CONNECT_TIMEOUT_SECONDS,
    )
    read_timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_READ_TIMEOUT_SECONDS,
        gt=MIN_TIME_SECONDS,
        le=MAX_PROVIDER_READ_TIMEOUT_SECONDS,
    )
    total_timeout_seconds: float = Field(
        default=DEFAULT_PROVIDER_TOTAL_TIMEOUT_SECONDS,
        gt=MIN_TIME_SECONDS,
        le=MAX_PROVIDER_TOTAL_TIMEOUT_SECONDS,
    )
    max_input_bytes: int = Field(
        default=DEFAULT_PROVIDER_MAX_INPUT_BYTES,
        gt=MIN_PROVIDER_BYTES,
        le=MAX_PROVIDER_INPUT_BYTES,
    )
    max_output_bytes: int = Field(
        default=DEFAULT_PROVIDER_MAX_OUTPUT_BYTES,
        gt=MIN_PROVIDER_BYTES,
        le=MAX_PROVIDER_OUTPUT_BYTES,
    )
    max_duration_seconds: float = Field(
        default=DEFAULT_PROVIDER_MAX_DURATION_SECONDS,
        gt=MIN_TIME_SECONDS,
        le=MAX_PROVIDER_DURATION_SECONDS,
    )
    cancellation_required: StrictBool = True
    max_retries: int = Field(
        default=DEFAULT_PROVIDER_MAX_RETRIES,
        ge=MIN_PROVIDER_RETRIES,
        le=MAX_PROVIDER_RETRIES,
    )
    transient_idempotent_retries_only: StrictBool = True
    idempotency_key_required: StrictBool = True
    max_concurrency: int = Field(
        default=DEFAULT_PROVIDER_MAX_CONCURRENCY,
        ge=MIN_PROVIDER_CONCURRENCY,
        le=MAX_PROVIDER_CONCURRENCY,
    )
    rate_limit_per_minute: int = Field(
        default=DEFAULT_PROVIDER_RATE_LIMIT_PER_MINUTE,
        ge=MIN_PROVIDER_RATE_LIMIT_PER_MINUTE,
        le=MAX_PROVIDER_RATE_LIMIT_PER_MINUTE,
    )
    redirects_allowed: StrictBool = False

    @field_validator(
        "max_input_bytes",
        "max_output_bytes",
        "max_retries",
        "max_concurrency",
        "rate_limit_per_minute",
        mode="before",
    )
    @classmethod
    def _strict_ints(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("provider integer limit must be an integer")
        return value

    @field_validator(
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "total_timeout_seconds",
        "max_duration_seconds",
        mode="before",
    )
    @classmethod
    def _strict_numbers(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("provider time limit must be numeric")
        return value

    @model_validator(mode="after")
    def _total_bounds_phases(self) -> ProviderExecutionLimits:
        if self.total_timeout_seconds < max(self.connect_timeout_seconds, self.read_timeout_seconds):
            raise ValueError("total timeout must bound each request phase")
        return self


class CloudRouteBinding(FrozenModel):
    """One confirmed provider-scoped egress route, never a cross product."""

    provider_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    egress_host: str = Field(min_length=1)
    credential_handle: str = Field(min_length=1)
    data_classes: tuple[str, ...] = Field(min_length=1)
    retention_ceiling_days: int = Field(ge=MIN_RETENTION_DAYS)
    estimated_cost_ceiling_usd: float = Field(ge=MIN_COST_USD)
    confirmed: StrictBool
    redirect_hosts: tuple[str, ...] = ()

    @field_validator("provider_id", "region", "egress_host", "credential_handle")
    @classmethod
    def _bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("data_classes", mode="before")
    @classmethod
    def _classes(cls, value: object) -> tuple[str, ...]:
        return _codes(value)

    @field_validator("redirect_hosts", mode="before")
    @classmethod
    def _redirects(cls, value: object) -> tuple[str, ...]:
        return _codes(value, allow_empty=True)

    @field_validator("retention_ceiling_days", mode="before")
    @classmethod
    def _strict_retention(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retention ceiling must be an integer")
        return value

    @field_validator("estimated_cost_ceiling_usd", mode="before")
    @classmethod
    def _strict_cost(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("cost ceiling must be numeric")
        return value


class ExecutionPolicy(FrozenModel):
    """Explicit local/cloud execution policy with exact routes."""

    allow_cloud: StrictBool = False
    cloud_execution_confirmed: StrictBool = False
    routes: tuple[CloudRouteBinding, ...] = ()
    limits: ProviderExecutionLimits = Field(default_factory=ProviderExecutionLimits)

    @field_validator("routes", mode="before")
    @classmethod
    def _routes(cls, value: object) -> tuple[object, ...]:
        try:
            routes = tuple(islice(iter(value), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
        except Exception:
            raise ValueError("cloud routes are invalid") from None
        if len(routes) > MAX_S3_REGISTRY_ADAPTERS:
            raise ValueError("cloud routes exceed their ceiling")
        return routes

    @model_validator(mode="after")
    def _cloud_coherence(self) -> ExecutionPolicy:
        if self.cloud_execution_confirmed and not self.allow_cloud:
            raise ValueError("cloud confirmation requires cloud opt-in")
        if self.allow_cloud and (not self.cloud_execution_confirmed or not self.routes):
            raise ValueError("cloud opt-in requires confirmed execution and a route")
        if not self.allow_cloud and self.routes:
            raise ValueError("cloud routes require cloud opt-in")
        digests = tuple(canonical_digest(route) for route in self.routes)
        if len(set(digests)) != len(digests):
            raise ValueError("cloud routes must be unique")
        return self


class ProviderRequest(FrozenModel):
    """One privacy-safe request bound to an exact provider route."""

    egress_host: str = Field(min_length=1)
    credential_handle: str = Field(min_length=1)
    data_classes: tuple[str, ...] = Field(min_length=1)
    retention_days: int = Field(ge=MIN_RETENTION_DAYS)
    territory: str = Field(min_length=1)
    grant_ids: tuple[str, ...] = Field(min_length=1)
    context: AuthorizationContext
    at_iso: str
    idempotency_key: str = "caller_managed"
    request_is_idempotent: StrictBool = True
    retry_class: str = "transient"
    cancellation_handle: str = "caller_managed"
    redirect_host: str | None = None

    @field_validator(
        "egress_host",
        "credential_handle",
        "idempotency_key",
        "retry_class",
        "cancellation_handle",
    )
    @classmethod
    def _bounded(cls, value: str) -> str:
        return BoundedCode(value)

    @field_validator("redirect_host")
    @classmethod
    def _redirect(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else None

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


class CloudExecutionApproval(FrozenModel):
    """Internally issued receipt for exact approved request, route, and limits."""

    provider_id: str
    region: str
    egress_host: str
    credential_handle: str
    data_classes: tuple[str, ...]
    retention_days: int
    territory: str
    grant_ids: tuple[str, ...]
    request_snapshot: ProviderRequest
    route_snapshot: CloudRouteBinding
    limits_snapshot: ProviderExecutionLimits
    policy_snapshot: ExecutionPolicy
    request_digest: Sha256
    route_digest: Sha256
    limits_digest: Sha256
    policy_digest: Sha256
    confirmed: StrictBool
    _issuance_proof: str | None = PrivateAttr(default=None)

    @field_validator("provider_id", "region", "egress_host", "credential_handle")
    @classmethod
    def _bounded(cls, value: str) -> str:
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

    @field_validator("retention_days", mode="before")
    @classmethod
    def _strict_retention(cls, value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("retention_days must be an integer")
        return value


def _approval_proof(approval: CloudExecutionApproval) -> str:
    payload_digest = canonical_digest(approval).encode("ascii")
    return hmac.new(_APPROVAL_SIGNING_KEY, payload_digest, "sha256").hexdigest()


@dataclass(frozen=True)
class AdapterSelection:
    """One validated adapter plus immutable execution-limit evidence."""

    resolved: ResolvedAdapter
    limits_snapshot: ProviderExecutionLimits
    limits_digest: Sha256
    cloud_approval: CloudExecutionApproval | None = None

    @property
    def instance(self) -> Adapter:
        return self.resolved.instance

    @property
    def descriptor(self) -> AdapterDescriptor:
        return self.resolved.descriptor

    @property
    def capability(self) -> CapabilityResult:
        return self.resolved.capability


class _AuthorizationLedger(Protocol):
    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        """Authorize exact cloud egress scope."""


def _sanitize_limits(value: object) -> ProviderExecutionLimits:
    return ProviderExecutionLimits.model_validate(_plain_fields(value, ProviderExecutionLimits))


def _sanitize_route(value: object) -> CloudRouteBinding:
    return CloudRouteBinding.model_validate(_plain_fields(value, CloudRouteBinding))


def _sanitize_policy(value: object) -> ExecutionPolicy:
    try:
        raw = _plain_fields(value, ExecutionPolicy)
        raw_routes = tuple(islice(iter(raw["routes"]), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
        if len(raw_routes) > MAX_S3_REGISTRY_ADAPTERS:
            raise ValueError("route ceiling exceeded")
        payload = {
            "allow_cloud": raw["allow_cloud"],
            "cloud_execution_confirmed": raw["cloud_execution_confirmed"],
            "routes": tuple(_sanitize_route(route) for route in raw_routes),
            "limits": _sanitize_limits(raw["limits"]),
        }
        return ExecutionPolicy.model_validate(payload)
    except Exception:
        logger.warning("execution policy ingress validation failed")
        raise _error("execution policy is invalid", "invalid_execution_policy") from None


def _sanitize_context(value: object) -> AuthorizationContext:
    if not isinstance(value, AuthorizationContext):
        raise TypeError("authorization context type mismatch")
    codes = {
        "operation": value.operation,
        "project_id": value.project_id,
        "character_id": value.character_id,
        "provider_class": value.provider_class,
    }
    checked = {name: BoundedCode(item) if item is not None else None for name, item in codes.items()}
    if value.territory is not None and not TERRITORY_RE.match(value.territory):
        raise ValueError("authorization territory is invalid")
    return AuthorizationContext(**checked, territory=value.territory)


def _sanitize_request(value: object) -> ProviderRequest:
    try:
        raw = _plain_fields(value, ProviderRequest)
        raw["context"] = _sanitize_context(raw["context"])
        return ProviderRequest.model_validate(raw)
    except Exception:
        logger.warning("provider request ingress validation failed")
        raise _error("provider request is invalid", "invalid_provider_request") from None


def _candidate_ids(values: object) -> tuple[str, ...]:
    try:
        collected = tuple(islice(iter(values), MAX_S3_REGISTRY_ADAPTERS + 1))  # type: ignore[arg-type]
        checked = _codes(collected)
    except (TypeError, ValueError):
        raise _error("provider candidates are invalid", "invalid_provider_candidates") from None
    if not checked:
        raise _error("provider candidates are invalid", "invalid_provider_candidates")
    return checked


def _matching_route(
    disclosure: CostDisclosure,
    request: ProviderRequest,
    policy: ExecutionPolicy,
) -> CloudRouteBinding:
    matches = tuple(
        route
        for route in policy.routes
        if route.provider_id == disclosure.provider_id
        and route.region == disclosure.region
        and route.egress_host == request.egress_host
        and route.credential_handle == request.credential_handle
    )
    if len(matches) != 1:
        raise _error("cloud execution policy denied the request", "cloud_execution_denied")
    return matches[0]


def _check_execution_limits(
    limits: ProviderExecutionLimits,
    route: CloudRouteBinding,
    request: ProviderRequest,
) -> None:
    denied = (
        (limits.idempotency_key_required and not request.idempotency_key)
        or (limits.cancellation_required and not request.cancellation_handle)
        or (
            limits.max_retries > MIN_PROVIDER_RETRIES
            and limits.transient_idempotent_retries_only
            and (not request.request_is_idempotent or request.retry_class != "transient")
        )
        or (
            request.redirect_host is not None
            and (not limits.redirects_allowed or request.redirect_host not in route.redirect_hosts)
        )
    )
    if denied:
        raise _error("cloud execution controls denied the request", "cloud_execution_denied")


def _check_route_scope(
    disclosure: CostDisclosure,
    route: CloudRouteBinding,
    request: ProviderRequest,
) -> None:
    allowed = (
        disclosure.confirmed
        and route.confirmed
        and set(request.data_classes) <= set(disclosure.data_classes)
        and set(request.data_classes) <= set(route.data_classes)
        and request.retention_days <= disclosure.retention_ceiling_days
        and request.retention_days <= route.retention_ceiling_days
        and disclosure.estimated_cost_usd_per_call <= route.estimated_cost_ceiling_usd
        and request.territory == request.context.territory
    )
    if not allowed:
        raise _error("cloud execution policy denied the request", "cloud_execution_denied")


def _authorize_cloud(
    disclosure: CostDisclosure,
    ledger: _AuthorizationLedger | None,
    request: ProviderRequest,
) -> tuple[str, ...]:
    if ledger is None:
        raise _error("cloud authorization request is required", "cloud_authorization_required")
    try:
        grants = ledger.authorize_cloud_egress(
            grant_ids=request.grant_ids,
            provider_id=disclosure.provider_id,
            data_classes=request.data_classes,
            territory=request.territory,
            retention_days=request.retention_days,
            at_iso=request.at_iso,
            context=request.context,
        )
        return _codes(grants)
    except (AuthorizationError, TypeError, ValueError):
        logger.warning("S2 cloud egress authorization denied")
        raise _error("cloud authorization was denied", "cloud_authorization_denied") from None


def _cloud_approval(
    disclosure: CostDisclosure,
    route: CloudRouteBinding,
    request: ProviderRequest,
    policy: ExecutionPolicy,
    grants: tuple[str, ...],
) -> CloudExecutionApproval:
    limits = policy.limits
    approval = CloudExecutionApproval(
        provider_id=disclosure.provider_id,
        region=disclosure.region,
        egress_host=request.egress_host,
        credential_handle=request.credential_handle,
        data_classes=request.data_classes,
        retention_days=request.retention_days,
        territory=request.territory,
        grant_ids=grants,
        request_snapshot=request,
        route_snapshot=route,
        limits_snapshot=limits,
        policy_snapshot=policy,
        request_digest=canonical_digest(request),
        route_digest=canonical_digest(route),
        limits_digest=canonical_digest(limits),
        policy_digest=canonical_digest(policy),
        confirmed=True,
    )
    approval.__pydantic_private__["_issuance_proof"] = _approval_proof(approval)
    return approval


def _sanitize_approval(value: object) -> CloudExecutionApproval:
    raw = _plain_fields(value, CloudExecutionApproval)
    raw["request_snapshot"] = _sanitize_request(raw["request_snapshot"])
    raw["route_snapshot"] = _sanitize_route(raw["route_snapshot"])
    raw["limits_snapshot"] = _sanitize_limits(raw["limits_snapshot"])
    raw["policy_snapshot"] = _sanitize_policy(raw["policy_snapshot"])
    return CloudExecutionApproval.model_validate(raw)


def _approval_is_coherent(
    approval: CloudExecutionApproval,
    policy: ExecutionPolicy | None,
) -> bool:
    request = approval.request_snapshot
    route = approval.route_snapshot
    limits = approval.limits_snapshot
    policy_snapshot = approval.policy_snapshot
    exact = (
        approval.confirmed
        and approval.provider_id == route.provider_id
        and approval.region == route.region
        and approval.egress_host == request.egress_host == route.egress_host
        and approval.credential_handle == request.credential_handle == route.credential_handle
        and approval.data_classes == request.data_classes
        and set(approval.data_classes) <= set(route.data_classes)
        and approval.retention_days == request.retention_days <= route.retention_ceiling_days
        and approval.territory == request.territory == request.context.territory
        and approval.grant_ids == request.grant_ids
        and approval.request_digest == canonical_digest(request)
        and approval.route_digest == canonical_digest(route)
        and approval.limits_digest == canonical_digest(limits)
        and approval.policy_digest == canonical_digest(policy_snapshot)
        and limits == policy_snapshot.limits
        and any(route == candidate for candidate in policy_snapshot.routes)
    )
    if policy is None:
        return exact
    return exact and policy_snapshot == policy


def validate_cloud_approval(
    approval: CloudExecutionApproval,
    policy: ExecutionPolicy | None = None,
) -> None:
    """Verify private issuance proof and exact request, route, policy, and limits."""

    try:
        if not isinstance(approval, CloudExecutionApproval):
            raise TypeError("approval type mismatch")
        checked_policy = _sanitize_policy(policy) if policy is not None else None
        checked = _sanitize_approval(approval)
        proof = approval._issuance_proof
        if not isinstance(proof, str) or not hmac.compare_digest(
            proof,
            _approval_proof(checked),
        ):
            raise ValueError("approval was not internally issued")
        if not _approval_is_coherent(checked, checked_policy):
            raise ValueError("approval snapshot mismatch")
    except Exception:
        logger.warning("cloud approval validation failed")
        raise _error("cloud execution policy changed", "cloud_policy_changed") from None


def _selection(
    resolved: ResolvedAdapter,
    limits: ProviderExecutionLimits,
    approval: CloudExecutionApproval | None = None,
) -> AdapterSelection:
    return AdapterSelection(
        resolved=resolved,
        limits_snapshot=limits,
        limits_digest=canonical_digest(limits),
        cloud_approval=approval,
    )


def select_adapter(
    registry: AdapterRegistry,
    candidate_ids: object,
    *,
    kind: str,
    policy: ExecutionPolicy,
    ledger: ConsentLedger | _AuthorizationLedger | None = None,
    request: ProviderRequest | None = None,
) -> AdapterSelection:
    """Validate ingress, select healthy local first, and issue exact cloud proof."""

    checked_policy = _sanitize_policy(policy)
    checked_request = _sanitize_request(request) if request is not None else None
    candidates = _candidate_ids(candidate_ids)
    descriptors = tuple((item, registry.declared_descriptor(item)) for item in candidates)
    local_ids = tuple(item for item, descriptor in descriptors if descriptor.locality is AdapterLocality.LOCAL)
    if local_ids:
        for adapter_id in local_ids:
            resolved = registry.resolve(adapter_id, kind=kind, locality=AdapterLocality.LOCAL)
            if resolved.capability.available:
                return _selection(resolved, checked_policy.limits)
        raise _error("local capability is unavailable", "local_capability_unavailable")
    if not checked_policy.allow_cloud or not checked_policy.cloud_execution_confirmed:
        raise _error("cloud execution was not explicitly confirmed", "cloud_execution_denied")
    if checked_request is None:
        raise _error("cloud authorization request is required", "cloud_authorization_required")
    for adapter_id, descriptor in descriptors:
        if descriptor.locality is not AdapterLocality.CLOUD or descriptor.cost_disclosure is None:
            continue
        disclosure = descriptor.cost_disclosure
        route = _matching_route(disclosure, checked_request, checked_policy)
        _check_route_scope(disclosure, route, checked_request)
        _check_execution_limits(checked_policy.limits, route, checked_request)
        resolved = registry.resolve(adapter_id, kind=kind, locality=AdapterLocality.CLOUD)
        if not resolved.capability.available:
            continue
        grants = _authorize_cloud(disclosure, ledger, checked_request)
        approval = _cloud_approval(disclosure, route, checked_request, checked_policy, grants)
        return _selection(resolved, checked_policy.limits, approval)
    raise _error("cloud capability is unavailable", "adapter_unavailable")
