"""Fail-closed S2 consent authorization, lineage, lease, and revocation runtime.

The runtime deliberately persists only opaque bounded ids and hashes in its
append-only event stream. Protected audio, biometric material, consent evidence,
PII, credentials, and host paths are outside this module's accepted surface.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import wraps
from threading import RLock
from typing import Any

from kinocut_sound._canonical import BoundedCode
from kinocut_sound._errors import SoundContractError
from kinocut_sound.consent import AuditEvent, ConsentGrant, ConsentState
from kinocut_sound.validation import ISO8601_RE


class AuthorizationError(SoundContractError):
    """Stable fail-closed authorization error."""


class AuthorizationBoundary(StrEnum):
    """Protected lifecycle boundaries that always require live grants."""

    INGEST = "ingest"
    EGRESS = "egress"
    GENERATION = "generation"
    CACHE_REUSE = "cache_reuse"
    ASSEMBLY = "assembly"
    COMMIT = "commit"
    EXPORT = "export"


class RevocationPolicy(StrEnum):
    """How a revocation request handles in-flight generation."""

    WAIT = "wait"
    CANCEL = "cancel"


class DerivativeDisposition(StrEnum):
    """Required outcome for a derivative reachable from a revoked grant."""

    QUARANTINE = "quarantine"
    DELETE = "delete"


class LeaseStatus(StrEnum):
    """Closed generation-lease lifecycle."""

    ACTIVE = "active"
    COMMITTED = "committed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class AuthorizationContext:
    """Requested grant scope; every populated field must be explicitly allowed."""

    operation: str
    project_id: str | None = None
    character_id: str | None = None
    provider_class: str | None = None
    territory: str | None = None


@dataclass(frozen=True)
class LedgerEvent:
    """One immutable privacy-safe append-only event."""

    sequence: int
    event: str
    at_iso: str
    actor_id: str
    grant_id: str | None = None
    lease_id: str | None = None
    asset_id: str | None = None
    detail_hash: str | None = None

    def to_dict(self) -> dict[str, int | str | None]:
        """Return the complete privacy-safe serialization."""

        return {
            "sequence": self.sequence,
            "event": self.event,
            "at_iso": self.at_iso,
            "actor_id": self.actor_id,
            "grant_id": self.grant_id,
            "lease_id": self.lease_id,
            "asset_id": self.asset_id,
            "detail_hash": self.detail_hash,
        }


@dataclass(frozen=True)
class AssetLineage:
    """Opaque asset lineage linking parents and direct consent grants."""

    asset_id: str
    direct_grant_ids: tuple[str, ...]
    parent_asset_ids: tuple[str, ...]


@dataclass(frozen=True)
class GenerationLease:
    """A bounded authorization snapshot for one generation operation."""

    lease_id: str
    grant_ids: tuple[str, ...]
    issued_at_iso: str
    expires_at_iso: str
    context: AuthorizationContext
    status: LeaseStatus


@dataclass(frozen=True)
class RevocationResult:
    """Observable result of a WAIT or CANCEL revocation request."""

    pending: bool
    in_flight_lease_ids: tuple[str, ...] = ()
    cancelled_lease_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DerivativeOutcome:
    """Quarantine or deletion outcome without protected artifact content."""

    asset_id: str
    grant_id: str
    disposition: DerivativeDisposition
    at_iso: str


@dataclass(frozen=True)
class _PendingRevocation:
    grant_id: str
    actor_id: str
    requested_at_iso: str


def _authorization_error(message: str, code: str) -> AuthorizationError:
    return AuthorizationError(message, code=code, suggested_action={"auto_fix": False})


def _parse_time(value: str) -> datetime:
    if not ISO8601_RE.match(value):
        raise _authorization_error("invalid authorization timestamp", "invalid_timestamp")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as exc:
        raise _authorization_error("invalid authorization timestamp", "invalid_timestamp") from exc


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _code(value: str, *, code: str = "invalid_identifier") -> str:
    try:
        return BoundedCode(value)
    except (TypeError, ValueError) as exc:
        raise _authorization_error("invalid opaque identifier", code) from exc


def _codes(values: tuple[str, ...]) -> tuple[str, ...]:
    checked = tuple(_code(value) for value in values)
    if len(set(checked)) != len(checked):
        raise _authorization_error("opaque identifiers must be unique", "duplicate_identifier")
    return checked


def _detail_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _locked(method: Any) -> Any:
    """Serialize one ledger lifecycle operation under its reentrant lock."""

    @wraps(method)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class ConsentLedger:
    """In-memory append-only authorization ledger and transitive lineage graph."""

    def __init__(self, *, max_lease_seconds: int) -> None:
        if (
            isinstance(max_lease_seconds, bool)
            or not isinstance(max_lease_seconds, int)
            or max_lease_seconds < 1
        ):
            raise _authorization_error("invalid lease ceiling", "invalid_lease_duration")
        self._max_lease_seconds = max_lease_seconds
        self._lock = RLock()
        self._events: list[LedgerEvent] = []
        self._grant_revisions: dict[str, list[ConsentGrant]] = {}
        self._lineage: dict[str, AssetLineage] = {}
        self._leases: dict[str, GenerationLease] = {}
        self._pending: dict[str, _PendingRevocation] = {}
        self._outcomes: dict[str, DerivativeOutcome] = {}

    @property
    def events(self) -> tuple[LedgerEvent, ...]:
        """Return an immutable view of the append-only event stream."""

        return tuple(self._events)

    def grant_history(self, grant_id: str) -> tuple[ConsentGrant, ...]:
        """Return immutable compare-before-replace revisions for one grant."""

        return tuple(self._grant_revisions.get(_code(grant_id), ()))

    def current_grant(self, grant_id: str) -> ConsentGrant:
        """Return the current revision or fail closed without echoing the id."""

        revisions = self._grant_revisions.get(_code(grant_id))
        if not revisions:
            raise _authorization_error("required consent grant is missing", "grant_missing")
        return revisions[-1]

    @_locked
    def register_grant(self, grant: ConsentGrant, *, at_iso: str, actor_id: str) -> None:
        """Append the initial revision and a privacy-safe registration event."""

        _parse_time(at_iso)
        _parse_time(grant.issue_iso)
        _parse_time(grant.expiry_iso)
        if grant.cloud_egress is not None:
            _parse_time(grant.cloud_egress.expiry_iso)
        actor_id = _code(actor_id)
        if grant.grant_id in self._grant_revisions:
            raise _authorization_error("consent grant already exists", "grant_already_exists")
        self._grant_revisions[grant.grant_id] = [grant]
        self._append_event(
            "grant_registered",
            at_iso,
            actor_id,
            grant_id=grant.grant_id,
            detail={"state": grant.state.value},
        )

    @_locked
    def authorize(
        self,
        boundary: AuthorizationBoundary,
        *,
        grant_ids: tuple[str, ...] = (),
        asset_ids: tuple[str, ...] = (),
        context: AuthorizationContext | None = None,
        at_iso: str,
    ) -> tuple[str, ...]:
        """Reauthorize direct and transitive grants at a protected boundary."""

        if context is None:
            raise _authorization_error("authorization scope is required", "grant_scope_missing")
        try:
            boundary = AuthorizationBoundary(boundary)
        except ValueError as exc:
            raise _authorization_error("unknown authorization boundary", "invalid_boundary") from exc
        _parse_time(at_iso)
        resolved = set(_codes(grant_ids))
        for asset_id in _codes(asset_ids):
            resolved.update(self.resolve_grants(asset_id))
        if not resolved:
            raise _authorization_error("authorization lineage is missing", "grant_missing")
        ordered = tuple(sorted(resolved))
        self._authorize_grants(ordered, at_iso=at_iso, context=context)
        self._append_event(
            "boundary_authorized",
            at_iso,
            "system:authorization",
            detail={"boundary": boundary.value, "grant_ids": ordered},
        )
        return ordered

    @_locked
    def acquire_lease(
        self,
        lease_id: str,
        *,
        grant_ids: tuple[str, ...],
        ttl_seconds: int,
        context: AuthorizationContext,
        at_iso: str,
        actor_id: str,
    ) -> GenerationLease:
        """Acquire a bounded lease only when every grant is currently live."""

        lease_id = _code(lease_id)
        actor_id = _code(actor_id)
        issued_at = _parse_time(at_iso)
        if lease_id in self._leases:
            raise _authorization_error("generation lease already exists", "lease_already_exists")
        if (
            isinstance(ttl_seconds, bool)
            or not isinstance(ttl_seconds, int)
            or not 1 <= ttl_seconds <= self._max_lease_seconds
        ):
            raise _authorization_error("invalid generation lease duration", "invalid_lease_duration")
        grant_ids = _codes(grant_ids)
        if not grant_ids:
            raise _authorization_error("generation lease requires consent", "grant_missing")
        self._authorize_grants(grant_ids, at_iso=at_iso, context=context)
        lease = GenerationLease(
            lease_id=lease_id,
            grant_ids=grant_ids,
            issued_at_iso=at_iso,
            expires_at_iso=_format_time(issued_at + timedelta(seconds=ttl_seconds)),
            status=LeaseStatus.ACTIVE,
            context=context,
        )
        self._leases[lease_id] = lease
        self._append_event(
            "lease_acquired",
            at_iso,
            actor_id,
            lease_id=lease_id,
            detail={"grant_ids": grant_ids, "expires_at_iso": lease.expires_at_iso},
        )
        return lease

    @_locked
    def commit_lease(
        self,
        lease_id: str,
        *,
        output_asset_id: str,
        parent_asset_ids: tuple[str, ...],
        at_iso: str,
        actor_id: str,
    ) -> AssetLineage:
        """Recheck a lease immediately before committing its output lineage."""

        lease_id = _code(lease_id)
        actor_id = _code(actor_id)
        output_asset_id = _code(output_asset_id)
        now = _parse_time(at_iso)
        lease = self._leases.get(lease_id)
        if lease is None:
            raise _authorization_error("generation lease is missing", "lease_missing")
        if lease.status is LeaseStatus.CANCELLED:
            raise _authorization_error("generation lease was cancelled", "lease_cancelled")
        if lease.status is not LeaseStatus.ACTIVE:
            raise _authorization_error("generation lease is not active", "lease_not_active")
        if now >= _parse_time(lease.expires_at_iso):
            self._replace_lease(lease, LeaseStatus.EXPIRED, at_iso, actor_id)
            self._finish_waiting_revocations(at_iso)
            raise _authorization_error("generation lease expired", "lease_expired")
        parent_grants: set[str] = set()
        for parent_id in _codes(parent_asset_ids):
            parent_grants.update(self.resolve_grants(parent_id))
        all_grants = tuple(sorted(set(lease.grant_ids) | parent_grants))
        self._authorize_grants(
            all_grants,
            at_iso=at_iso,
            context=lease.context,
            allow_pending=frozenset(lease.grant_ids),
        )
        lineage = self._store_asset(output_asset_id, lease.grant_ids, parent_asset_ids)
        self._replace_lease(lease, LeaseStatus.COMMITTED, at_iso, actor_id)
        self._append_event(
            "asset_committed",
            at_iso,
            actor_id,
            lease_id=lease_id,
            asset_id=output_asset_id,
            detail={"grant_ids": lease.grant_ids, "parent_asset_ids": parent_asset_ids},
        )
        self._finish_waiting_revocations(at_iso)
        return lineage

    @_locked
    def revoke(
        self,
        grant_id: str,
        *,
        expected_state: ConsentState,
        policy: RevocationPolicy,
        at_iso: str,
        actor_id: str,
    ) -> RevocationResult:
        """Compare state, block new leases, then wait for or cancel active work."""

        grant_id = _code(grant_id)
        actor_id = _code(actor_id)
        try:
            policy = RevocationPolicy(policy)
        except ValueError as exc:
            raise _authorization_error("invalid revocation policy", "invalid_revocation_policy") from exc
        _parse_time(at_iso)
        grant = self.current_grant(grant_id)
        if grant.state is not expected_state or grant_id in self._pending:
            raise _authorization_error("consent state changed", "consent_state_conflict")
        active = self._active_lease_ids(grant_id, at_iso)
        if policy is RevocationPolicy.WAIT and active:
            self._pending[grant_id] = _PendingRevocation(grant_id, actor_id, at_iso)
            self._append_event(
                "revocation_waiting",
                at_iso,
                actor_id,
                grant_id=grant_id,
                detail={"lease_ids": active},
            )
            return RevocationResult(pending=True, in_flight_lease_ids=active)
        cancelled = self._cancel_leases(active, at_iso, actor_id)
        self._transition_revoked(grant_id, at_iso, actor_id)
        return RevocationResult(pending=False, cancelled_lease_ids=cancelled)

    @_locked
    def abort_lease(self, lease_id: str, *, at_iso: str, actor_id: str) -> None:
        """Abort active work and finalize revocation waiting on that lease."""

        lease_id = _code(lease_id)
        actor_id = _code(actor_id)
        _parse_time(at_iso)
        lease = self._leases.get(lease_id)
        if lease is None:
            raise _authorization_error("generation lease is missing", "lease_missing")
        if lease.status is not LeaseStatus.ACTIVE:
            raise _authorization_error("generation lease is not active", "lease_not_active")
        self._replace_lease(lease, LeaseStatus.CANCELLED, at_iso, actor_id)
        self._finish_waiting_revocations(at_iso)

    @_locked
    def record_asset(
        self,
        asset_id: str,
        *,
        direct_grant_ids: tuple[str, ...],
        parent_asset_ids: tuple[str, ...],
        context: AuthorizationContext,
        at_iso: str,
    ) -> AssetLineage:
        """Record immutable lineage after reauthorizing all direct and parent grants."""

        _parse_time(at_iso)
        all_grants = set(_codes(direct_grant_ids))
        for parent_id in _codes(parent_asset_ids):
            all_grants.update(self.resolve_grants(parent_id))
        if not all_grants:
            raise _authorization_error("asset consent lineage is missing", "grant_missing")
        self._authorize_grants(
            tuple(sorted(all_grants)),
            at_iso=at_iso,
            context=context,
        )
        lineage = self._store_asset(asset_id, direct_grant_ids, parent_asset_ids)
        self._append_event(
            "asset_lineage_recorded",
            at_iso,
            "system:lineage",
            asset_id=lineage.asset_id,
            detail={
                "grant_ids": tuple(sorted(all_grants)),
                "parent_asset_ids": lineage.parent_asset_ids,
            },
        )
        return lineage

    def resolve_grants(self, asset_id: str) -> tuple[str, ...]:
        """Resolve every grant transitively through parents, failing on gaps."""

        asset_id = _code(asset_id)
        resolved: set[str] = set()
        visiting: set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in visiting:
                raise _authorization_error("asset lineage cycle detected", "lineage_cycle")
            lineage = self._lineage.get(current_id)
            if lineage is None:
                raise _authorization_error("asset lineage is missing", "lineage_missing")
            visiting.add(current_id)
            resolved.update(lineage.direct_grant_ids)
            for parent_id in lineage.parent_asset_ids:
                visit(parent_id)
            visiting.remove(current_id)

        visit(asset_id)
        return tuple(sorted(resolved))

    def outcome_for(self, asset_id: str) -> DerivativeOutcome:
        """Return the enforced quarantine/deletion outcome for one asset."""

        outcome = self._outcomes.get(_code(asset_id))
        if outcome is None:
            raise _authorization_error("derivative outcome is missing", "outcome_missing")
        return outcome

    @_locked
    def authorize_blend(
        self,
        blend_grant_id: str,
        *,
        context: AuthorizationContext,
        at_iso: str,
    ) -> tuple[str, ...]:
        """Require the composite grant and every named source grant independently."""

        if context.operation != "voice_blend":
            raise _authorization_error("blend scope is denied", "grant_scope_denied")
        grant = self.current_grant(blend_grant_id)
        if grant.blend is None:
            raise _authorization_error("blend authorization is missing", "blend_grant_missing")
        grant_ids = tuple(sorted((*grant.blend.source_grant_ids, grant.grant_id)))
        self._authorize_grants(
            grant_ids,
            at_iso=at_iso,
            context=context,
        )
        return grant_ids

    @_locked
    def authorize_cloud_egress(
        self,
        *,
        grant_ids: tuple[str, ...],
        provider_id: str,
        data_classes: tuple[str, ...],
        territory: str,
        retention_days: int,
        at_iso: str,
        context: AuthorizationContext,
    ) -> tuple[str, ...]:
        """Require exact per-grant provider/data/territory/retention authorization."""

        grant_ids = _codes(grant_ids)
        if not grant_ids or not data_classes:
            raise _authorization_error("cloud egress is denied", "cloud_egress_denied")
        try:
            provider_id = BoundedCode(provider_id)
            data_classes = tuple(BoundedCode(value) for value in data_classes)
            territory = BoundedCode(territory)
        except (TypeError, ValueError) as exc:
            raise _authorization_error("cloud egress is denied", "cloud_egress_denied") from exc
        if isinstance(retention_days, bool) or not isinstance(retention_days, int):
            raise _authorization_error("cloud egress is denied", "cloud_egress_denied")
        self._authorize_grants(grant_ids, at_iso=at_iso, context=context)
        for grant_id in grant_ids:
            grant = self.current_grant(grant_id)
            egress = grant.cloud_egress
            allowed = (
                egress is not None
                and egress.provider_id == provider_id
                and "cloud" in grant.scope.provider_classes
                and grant.scope.territory == territory
                and egress.territory == territory
                and set(data_classes) <= set(egress.data_classes)
                and 0 <= retention_days <= egress.retention_ceiling_days
                and _parse_time(at_iso) < _parse_time(egress.expiry_iso)
            )
            if not allowed:
                raise _authorization_error("cloud egress is denied", "cloud_egress_denied")
        self._append_event(
            "cloud_egress_authorized",
            at_iso,
            "system:authorization",
            detail={
                "grant_ids": grant_ids,
                "provider_id": provider_id,
                "data_classes": data_classes,
                "territory": territory,
                "retention_days": retention_days,
            },
        )
        return grant_ids

    def _authorize_grants(
        self,
        grant_ids: tuple[str, ...],
        *,
        at_iso: str,
        context: AuthorizationContext,
        allow_pending: frozenset[str] = frozenset(),
    ) -> None:
        now = _parse_time(at_iso)
        for grant_id in grant_ids:
            revisions = self._grant_revisions.get(grant_id)
            if not revisions:
                raise _authorization_error("required consent grant is not authorized", "grant_missing")
            grant = revisions[-1]
            if grant.state is ConsentState.REVOKED:
                raise _authorization_error("required consent grant is not authorized", "grant_revoked")
            if now < _parse_time(grant.issue_iso):
                raise _authorization_error("consent grant is not yet valid", "grant_not_yet_valid")
            if grant.state in {ConsentState.EXPIRED, ConsentState.MISSING} or now >= _parse_time(grant.expiry_iso):
                code = "grant_missing" if grant.state is ConsentState.MISSING else "grant_expired"
                raise _authorization_error("required consent grant is not authorized", code)
            if grant.state is not ConsentState.LIVE:
                raise _authorization_error("required consent grant is not authorized", "grant_not_live")
            if grant_id in self._pending and grant_id not in allow_pending:
                raise _authorization_error("consent revocation is pending", "revocation_pending")
            self._enforce_scope(grant, context)

    def _enforce_scope(self, grant: ConsentGrant, context: AuthorizationContext) -> None:
        if not isinstance(context, AuthorizationContext) or not isinstance(context.operation, str):
            raise _authorization_error("consent scope is invalid", "grant_scope_invalid")
        try:
            requested = (
                (_code(context.operation), grant.scope.operations),
                (
                    _code(context.project_id) if context.project_id is not None else None,
                    grant.scope.project_ids,
                ),
                (
                    _code(context.character_id) if context.character_id is not None else None,
                    grant.scope.character_ids,
                ),
                (
                    _code(context.provider_class) if context.provider_class is not None else None,
                    grant.scope.provider_classes,
                ),
            )
            territory = _code(context.territory) if context.territory is not None else None
        except AuthorizationError as exc:
            raise _authorization_error("consent scope is invalid", "grant_scope_invalid") from exc
        denied = any(allowed and (value is None or value not in allowed) for value, allowed in requested)
        denied = denied or territory is None or territory != grant.scope.territory
        if denied:
            raise _authorization_error("consent scope is denied", "grant_scope_denied")

    def _append_event(
        self,
        event: str,
        at_iso: str,
        actor_id: str,
        *,
        grant_id: str | None = None,
        lease_id: str | None = None,
        asset_id: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        entry = LedgerEvent(
            sequence=len(self._events) + 1,
            event=_code(event),
            at_iso=at_iso,
            actor_id=_code(actor_id),
            grant_id=grant_id,
            lease_id=lease_id,
            asset_id=asset_id,
            detail_hash=_detail_hash(detail) if detail is not None else None,
        )
        self._events.append(entry)

    def _store_asset(
        self,
        asset_id: str,
        grant_ids: tuple[str, ...],
        parent_asset_ids: tuple[str, ...],
    ) -> AssetLineage:
        asset_id = _code(asset_id)
        grant_ids = _codes(grant_ids)
        parent_asset_ids = _codes(parent_asset_ids)
        if asset_id in self._lineage:
            raise _authorization_error("asset lineage already exists", "lineage_already_exists")
        for parent_id in parent_asset_ids:
            if parent_id not in self._lineage:
                raise _authorization_error("asset parent lineage is missing", "lineage_missing")
        lineage = AssetLineage(asset_id, grant_ids, parent_asset_ids)
        self._lineage[asset_id] = lineage
        return lineage

    def _replace_lease(
        self,
        lease: GenerationLease,
        status: LeaseStatus,
        at_iso: str,
        actor_id: str,
    ) -> None:
        self._leases[lease.lease_id] = GenerationLease(
            lease_id=lease.lease_id,
            grant_ids=lease.grant_ids,
            issued_at_iso=lease.issued_at_iso,
            expires_at_iso=lease.expires_at_iso,
            context=lease.context,
            status=status,
        )
        self._append_event(
            f"lease_{status.value}",
            at_iso,
            actor_id,
            lease_id=lease.lease_id,
            detail={"grant_ids": lease.grant_ids},
        )

    def _active_lease_ids(self, grant_id: str, at_iso: str) -> tuple[str, ...]:
        now = _parse_time(at_iso)
        active: list[str] = []
        for lease in tuple(self._leases.values()):
            if lease.status is not LeaseStatus.ACTIVE:
                continue
            if now >= _parse_time(lease.expires_at_iso):
                self._replace_lease(lease, LeaseStatus.EXPIRED, at_iso, "system:authorization")
            elif grant_id in lease.grant_ids:
                active.append(lease.lease_id)
        return tuple(sorted(active))

    def _cancel_leases(
        self,
        lease_ids: tuple[str, ...],
        at_iso: str,
        actor_id: str,
    ) -> tuple[str, ...]:
        for lease_id in lease_ids:
            self._replace_lease(self._leases[lease_id], LeaseStatus.CANCELLED, at_iso, actor_id)
        return lease_ids

    def _finish_waiting_revocations(self, at_iso: str) -> None:
        for grant_id, pending in tuple(self._pending.items()):
            if self._active_lease_ids(grant_id, at_iso):
                continue
            del self._pending[grant_id]
            self._transition_revoked(grant_id, at_iso, pending.actor_id)

    def _transition_revoked(self, grant_id: str, at_iso: str, actor_id: str) -> None:
        current = self.current_grant(grant_id)
        audit_log = (*current.audit_log, AuditEvent(event="revoked", at_iso=at_iso, actor=actor_id))
        replacement = ConsentGrant.model_validate(
            {
                **current.model_dump(mode="python"),
                "state": ConsentState.REVOKED,
                "audit_log": audit_log,
            }
        )
        self._grant_revisions[grant_id].append(replacement)
        self._append_event("grant_revoked", at_iso, actor_id, grant_id=grant_id)
        self._apply_derivative_policy(replacement, at_iso)

    def _apply_derivative_policy(self, grant: ConsentGrant, at_iso: str) -> None:
        delete_codes = {"delete_on_revocation", "delete_after_use"}
        disposition = (
            DerivativeDisposition.DELETE
            if grant.retention.biometric_retention in delete_codes
            else DerivativeDisposition.QUARANTINE
        )
        for asset_id in tuple(self._lineage):
            if grant.grant_id not in self.resolve_grants(asset_id):
                continue
            existing = self._outcomes.get(asset_id)
            if existing is not None and existing.disposition is DerivativeDisposition.DELETE:
                continue
            outcome = DerivativeOutcome(asset_id, grant.grant_id, disposition, at_iso)
            self._outcomes[asset_id] = outcome
            self._append_event(
                f"derivative_{disposition.value}",
                at_iso,
                "system:authorization",
                grant_id=grant.grant_id,
                asset_id=asset_id,
                detail={"disposition": disposition.value},
            )
