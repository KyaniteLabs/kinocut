"""Authorization-aware, content-bound S3 cache index."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import logging
from typing import Protocol

from pydantic import StrictBool, TypeAdapter, field_validator, model_validator

from kinocut_sound._canonical import BoundedCode, FrozenModel, Sha256
from kinocut_sound._errors import SoundContractError
from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    DerivativeDisposition,
    DerivativeOutcome,
)
from kinocut_sound.limits import MAX_FINGERPRINT_ITEMS, MAX_S3_CACHE_ENTRIES
from kinocut_sound.provider_policy import (
    CloudExecutionApproval,
    ExecutionPolicy,
    validate_cloud_approval,
)
from kinocut_sound.registry import RegistryError
from kinocut_sound.s3_fingerprint import CompleteRenderFingerprint

logger = logging.getLogger(__name__)


class CacheError(SoundContractError):
    """Stable fail-closed cache error."""


def _error(message: str, code: str) -> CacheError:
    return CacheError(message, code=code, suggested_action={"auto_fix": False})


class AuthorizedLineage(FrozenModel):
    """Trusted S2 lineage source; caller-supplied grants are never accepted."""

    pre_recorded_output: StrictBool = False
    parent_asset_ids: tuple[str, ...] = ()
    actor_id: str | None = None
    lease_id: str | None = None

    @field_validator("parent_asset_ids", mode="before")
    @classmethod
    def _parents(cls, value: object) -> tuple[str, ...]:
        return _bounded_codes(value, allow_empty=True)

    @field_validator("actor_id")
    @classmethod
    def _actor(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else None

    @model_validator(mode="after")
    def _lease_actor_coherence(self) -> AuthorizedLineage:
        if self.lease_id is not None and self.actor_id is None:
            raise ValueError("leased lineage requires an actor")
        if self.lease_id is None and self.actor_id is not None:
            raise ValueError("lineage actor requires a lease")
        return self

    @field_validator("lease_id")
    @classmethod
    def _lease(cls, value: str | None) -> str | None:
        return BoundedCode(value) if value is not None else None


class _Ledger(Protocol):
    def authorize(self, boundary: AuthorizationBoundary, **kwargs: object) -> tuple[str, ...]:
        """Authorize a protected cache boundary."""

    def resolve_grants(self, asset_id: str) -> tuple[str, ...]:
        """Resolve effective grants from recorded lineage."""

    def record_asset(self, asset_id: str, **kwargs: object) -> object:
        """Record cache artifact lineage."""

    def commit_lease(self, lease_id: str, **kwargs: object) -> object:
        """Commit a trusted leased output."""

    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        """Authorize exact cloud data reuse."""


@dataclass(frozen=True)
class CacheEntry:
    """Privacy-safe immutable cache index entry."""

    cache_key: str
    fingerprint_digest: str
    stage_cue_id: str
    artifact_id: str
    artifact_digest: str
    protected: bool
    grant_ids: tuple[str, ...] = ()
    cloud_approval: CloudExecutionApproval | None = None


def _bounded_codes(values: object, *, allow_empty: bool = False) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_FINGERPRINT_ITEMS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("cache lineage traversal failed")
        raise _error("cache lineage is invalid", "invalid_cache_lineage") from None
    if len(items) > MAX_FINGERPRINT_ITEMS or (not items and not allow_empty):
        raise _error("cache lineage is invalid", "invalid_cache_lineage")
    try:
        checked = tuple(BoundedCode(item) for item in items)
    except (TypeError, ValueError):
        raise _error("cache lineage is invalid", "invalid_cache_lineage") from None
    if len(set(checked)) != len(checked):
        raise _error("cache lineage must be unique", "invalid_cache_lineage")
    return tuple(sorted(checked))


def _digest(value: object) -> str:
    try:
        return TypeAdapter(Sha256).validate_python(value)
    except Exception:
        raise _error("cache content digest is invalid", "invalid_cache_content") from None


def _require_complete(value: object) -> CompleteRenderFingerprint:
    if not isinstance(value, CompleteRenderFingerprint):
        raise _error("cache fingerprint is incomplete", "incomplete_render_fingerprint")
    return value


def _trusted_grants(
    ledger: _Ledger,
    artifact_id: str,
    lineage: AuthorizedLineage,
    context: AuthorizationContext,
    at_iso: str,
) -> tuple[str, ...]:
    choices = (
        int(lineage.pre_recorded_output)
        + (lineage.lease_id is not None)
        + (bool(lineage.parent_asset_ids) and lineage.lease_id is None)
    )
    if choices != 1:
        raise _error("trusted output lineage is required", "trusted_lineage_required")
    try:
        if lineage.lease_id is not None:
            ledger.commit_lease(
                lineage.lease_id,
                output_asset_id=artifact_id,
                parent_asset_ids=lineage.parent_asset_ids,
                at_iso=at_iso,
                actor_id=lineage.actor_id,
            )
        elif lineage.parent_asset_ids:
            ledger.record_asset(
                artifact_id,
                direct_grant_ids=(),
                parent_asset_ids=lineage.parent_asset_ids,
                context=context,
                at_iso=at_iso,
            )
        return _bounded_codes(ledger.resolve_grants(artifact_id))
    except (AuthorizationError, AttributeError, TypeError, ValueError, CacheError):
        logger.warning("cache trusted lineage resolution denied")
        raise _error("cache authorization was denied", "cache_authorization_denied") from None


class AuthorizationAwareCache:
    """Bounded cache with explicit public/protected APIs and live S2 rechecks."""

    def __init__(self, *, max_entries: int = MAX_S3_CACHE_ENTRIES) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or not 1 <= max_entries <= MAX_S3_CACHE_ENTRIES
        ):
            raise _error("cache capacity is invalid", "invalid_cache_capacity")
        self._max_entries = max_entries
        self._entries: dict[str, CacheEntry] = {}

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    def _identity(
        self,
        fingerprint: object,
        stage_cue_id: str,
        artifact_id: str,
        artifact_digest: object,
    ) -> tuple[CompleteRenderFingerprint, str, str, str, str]:
        checked = _require_complete(fingerprint)
        try:
            stage = BoundedCode(stage_cue_id)
            artifact = BoundedCode(artifact_id)
        except (TypeError, ValueError):
            raise _error("cache identity is invalid", "invalid_cache_identity") from None
        digest = _digest(artifact_digest)
        key = checked.cache_key(stage)
        if key not in self._entries and len(self._entries) >= self._max_entries:
            raise _error("cache capacity exceeded", "cache_capacity_exceeded")
        return checked, stage, artifact, digest, key

    def _store_entry(
        self,
        fingerprint: object,
        stage_cue_id: str,
        artifact_id: str,
        artifact_digest: object,
        *,
        protected: bool,
        grant_ids: tuple[str, ...] = (),
        cloud_approval: CloudExecutionApproval | None = None,
    ) -> CacheEntry:
        checked, stage, artifact, digest, key = self._identity(fingerprint, stage_cue_id, artifact_id, artifact_digest)
        entry = CacheEntry(
            cache_key=key,
            fingerprint_digest=checked.digest(),
            stage_cue_id=stage,
            artifact_id=artifact,
            artifact_digest=digest,
            protected=protected,
            grant_ids=grant_ids,
            cloud_approval=cloud_approval,
        )
        self._entries[key] = entry
        return entry

    def store_unprotected(
        self,
        fingerprint: object,
        stage_cue_id: str,
        *,
        artifact_id: str,
        artifact_digest: object,
    ) -> CacheEntry:
        """Store explicitly public/unprotected output without an S2 grant."""

        return self._store_entry(
            fingerprint,
            stage_cue_id,
            artifact_id,
            artifact_digest,
            protected=False,
        )

    def store_authorized(
        self,
        fingerprint: object,
        stage_cue_id: str,
        *,
        artifact_id: str,
        artifact_digest: object,
        lineage: AuthorizedLineage,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
        cloud_approval: CloudExecutionApproval | None = None,
    ) -> CacheEntry:
        """Store protected output using only pre-existing trusted S2 lineage."""

        try:
            checked_lineage = AuthorizedLineage.model_validate(lineage.model_dump(mode="python"))
        except Exception:
            raise _error("trusted output lineage is invalid", "trusted_lineage_required") from None
        if cloud_approval is not None:
            try:
                validate_cloud_approval(cloud_approval)
            except RegistryError:
                raise _error("cloud approval is invalid", "cache_cloud_unconfirmed") from None
        grants = _trusted_grants(ledger, BoundedCode(artifact_id), checked_lineage, context, at_iso)
        return self._store_entry(
            fingerprint,
            stage_cue_id,
            artifact_id,
            artifact_digest,
            protected=True,
            grant_ids=grants,
            cloud_approval=cloud_approval,
        )

    def _hit(
        self,
        fingerprint: object,
        stage_cue_id: str,
        content_digest: object,
        *,
        protected: bool,
    ) -> CacheEntry:
        checked = _require_complete(fingerprint)
        try:
            stage = BoundedCode(stage_cue_id)
        except (TypeError, ValueError):
            raise _error("cache identity is invalid", "invalid_cache_identity") from None
        key = checked.cache_key(stage)
        entry = self._entries.get(key)
        if entry is None or entry.protected is not protected:
            raise _error("cache entry was not found", "cache_miss")
        valid = entry.cache_key == key and entry.fingerprint_digest == checked.digest() and entry.stage_cue_id == stage
        if not valid:
            self.evict_asset(entry.artifact_id)
            raise _error("cache entry failed integrity validation", "cache_tampered")
        if entry.artifact_digest != _digest(content_digest):
            self.evict_asset(entry.artifact_id)
            raise _error("cache content digest changed", "cache_content_mismatch")
        return entry

    def reuse_unprotected(
        self,
        fingerprint: object,
        stage_cue_id: str,
        *,
        content_digest: object,
    ) -> CacheEntry:
        return self._hit(fingerprint, stage_cue_id, content_digest, protected=False)

    def _reauthorize(
        self,
        entry: CacheEntry,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
        execution_policy: ExecutionPolicy | None,
    ) -> None:
        try:
            ledger.authorize(
                AuthorizationBoundary.CACHE_REUSE,
                grant_ids=entry.grant_ids,
                asset_ids=(entry.artifact_id,),
                context=context,
                at_iso=at_iso,
            )
            if entry.cloud_approval is not None:
                if execution_policy is None:
                    raise RegistryError("policy missing", code="cloud_policy_changed")
                validate_cloud_approval(entry.cloud_approval, execution_policy)
                approval = entry.cloud_approval
                ledger.authorize_cloud_egress(
                    grant_ids=entry.grant_ids,
                    provider_id=approval.provider_id,
                    data_classes=approval.data_classes,
                    territory=approval.territory,
                    retention_days=approval.retention_days,
                    at_iso=at_iso,
                    context=context,
                )
        except RegistryError:
            self.evict_asset(entry.artifact_id)
            raise _error("cached cloud policy changed", "cache_cloud_policy_changed") from None
        except AuthorizationError:
            logger.warning("cache reuse authorization denied")
            self.evict_asset(entry.artifact_id)
            raise _error("cache authorization was denied", "cache_authorization_denied") from None

    def reuse_authorized(
        self,
        fingerprint: object,
        stage_cue_id: str,
        *,
        content_digest: object,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
        execution_policy: ExecutionPolicy | None = None,
    ) -> CacheEntry:
        entry = self._hit(fingerprint, stage_cue_id, content_digest, protected=True)
        self._reauthorize(entry, ledger, context, at_iso, execution_policy)
        return entry

    def evict_asset(self, artifact_id: str) -> int:
        """Evict every stage/cue alias for one opaque artifact id."""

        try:
            checked = BoundedCode(artifact_id)
        except (TypeError, ValueError):
            raise _error("cache artifact id is invalid", "invalid_cache_identity") from None
        keys = tuple(key for key, entry in self._entries.items() if entry.artifact_id == checked)
        for key in keys:
            del self._entries[key]
        return len(keys)

    def apply_derivative_outcome(self, outcome: DerivativeOutcome) -> int:
        """Evict all aliases when S2 quarantines or deletes a derivative."""

        if outcome.disposition not in {
            DerivativeDisposition.QUARANTINE,
            DerivativeDisposition.DELETE,
        }:
            raise _error("derivative outcome is invalid", "invalid_derivative_outcome")
        return self.evict_asset(outcome.asset_id)
