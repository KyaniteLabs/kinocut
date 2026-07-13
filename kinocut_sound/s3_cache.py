"""Authorization-aware, fingerprint-bound S3 cache index."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import islice
import logging
from typing import Protocol

from kinocut_sound._canonical import BoundedCode
from kinocut_sound._errors import SoundContractError
from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    DerivativeDisposition,
    DerivativeOutcome,
)
from kinocut_sound.capability import CostDisclosure
from kinocut_sound.limits import (
    MAX_FINGERPRINT_ITEMS,
    MAX_S3_CACHE_ENTRIES,
)
from kinocut_sound.render_fingerprint import RenderFingerprint
from kinocut_sound.s3_fingerprint import S3_REQUIRED_COMPONENT_ROLES

logger = logging.getLogger(__name__)


class CacheError(SoundContractError):
    """Stable fail-closed cache error."""


def _error(message: str, code: str) -> CacheError:
    return CacheError(message, code=code, suggested_action={"auto_fix": False})


class _Ledger(Protocol):
    def authorize(self, boundary: AuthorizationBoundary, **kwargs: object) -> tuple[str, ...]:
        """Authorize a protected cache boundary."""

    def record_asset(self, asset_id: str, **kwargs: object) -> object:
        """Record cache artifact lineage."""

    def authorize_cloud_egress(self, **kwargs: object) -> tuple[str, ...]:
        """Authorize exact cloud data reuse."""


@dataclass(frozen=True)
class CacheEntry:
    """Privacy-safe immutable cache index entry."""

    cache_key: str
    fingerprint_digest: str
    stage_cue_id: str
    artifact_id: str
    grant_ids: tuple[str, ...]
    cloud_disclosure: CostDisclosure | None = None


def _bounded_codes(values: object) -> tuple[str, ...]:
    try:
        items = tuple(islice(iter(values), MAX_FINGERPRINT_ITEMS + 1))  # type: ignore[arg-type]
    except Exception:
        logger.warning("cache grant traversal failed")
        raise _error("cache grant lineage is invalid", "invalid_cache_lineage") from None
    if not items or len(items) > MAX_FINGERPRINT_ITEMS:
        raise _error("cache grant lineage is invalid", "invalid_cache_lineage")
    try:
        checked = tuple(BoundedCode(item) for item in items)
    except (TypeError, ValueError):
        raise _error("cache grant lineage is invalid", "invalid_cache_lineage") from None
    if len(set(checked)) != len(checked):
        raise _error("cache grant lineage must be unique", "invalid_cache_lineage")
    return tuple(sorted(checked))


def _require_complete(fingerprint: RenderFingerprint) -> None:
    try:
        components = tuple(islice(iter(fingerprint.components), MAX_FINGERPRINT_ITEMS + 1))
        roles = {BoundedCode(component.role) for component in components}
    except Exception:
        logger.warning("cache fingerprint validation failed")
        raise _error("cache fingerprint is invalid", "incomplete_render_fingerprint") from None
    if len(components) > MAX_FINGERPRINT_ITEMS or not roles >= S3_REQUIRED_COMPONENT_ROLES:
        raise _error("cache fingerprint is incomplete", "incomplete_render_fingerprint")


def _authorize_store(
    ledger: _Ledger,
    artifact_id: str,
    grant_ids: tuple[str, ...],
    context: AuthorizationContext,
    at_iso: str,
) -> None:
    try:
        ledger.authorize(
            AuthorizationBoundary.COMMIT,
            grant_ids=grant_ids,
            context=context,
            at_iso=at_iso,
        )
        ledger.record_asset(
            artifact_id,
            direct_grant_ids=grant_ids,
            parent_asset_ids=(),
            context=context,
            at_iso=at_iso,
        )
    except AuthorizationError:
        logger.warning("cache store authorization denied")
        raise _error("cache authorization was denied", "cache_authorization_denied") from None


class AuthorizationAwareCache:
    """Bounded cache whose every hit rechecks live S2 authorization."""

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
        """Return the number of stage/cue aliases in the index."""

        return len(self._entries)

    def store(
        self,
        fingerprint: RenderFingerprint,
        stage_cue_id: str,
        *,
        artifact_id: str,
        grant_ids: object,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
        cloud_disclosure: CostDisclosure | None = None,
    ) -> CacheEntry:
        """Authorize and store one complete fingerprint/stage/cue binding."""

        _require_complete(fingerprint)
        try:
            artifact_id = BoundedCode(artifact_id)
            stage_cue_id = BoundedCode(stage_cue_id)
        except (TypeError, ValueError):
            raise _error("cache identity is invalid", "invalid_cache_identity") from None
        checked_grants = _bounded_codes(grant_ids)
        key = fingerprint.cache_key(stage_cue_id)
        if key not in self._entries and len(self._entries) >= self._max_entries:
            raise _error("cache capacity exceeded", "cache_capacity_exceeded")
        _authorize_store(ledger, artifact_id, checked_grants, context, at_iso)
        entry = CacheEntry(
            cache_key=key,
            fingerprint_digest=fingerprint.digest(),
            stage_cue_id=stage_cue_id,
            artifact_id=artifact_id,
            grant_ids=checked_grants,
            cloud_disclosure=cloud_disclosure,
        )
        self._entries[key] = entry
        return entry

    def _validate_hit(
        self,
        entry: CacheEntry,
        key: str,
        fingerprint: RenderFingerprint,
        stage_cue_id: str,
    ) -> None:
        expected_digest = fingerprint.digest()
        valid = (
            entry.cache_key == key
            and entry.fingerprint_digest == expected_digest
            and entry.stage_cue_id == stage_cue_id
            and fingerprint.cache_key(entry.stage_cue_id) == key
        )
        if not valid:
            self._entries.pop(key, None)
            raise _error("cache entry failed integrity validation", "cache_tampered")

    def _authorize_hit(
        self,
        entry: CacheEntry,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> None:
        try:
            ledger.authorize(
                AuthorizationBoundary.CACHE_REUSE,
                grant_ids=entry.grant_ids,
                asset_ids=(entry.artifact_id,),
                context=context,
                at_iso=at_iso,
            )
            if entry.cloud_disclosure is not None:
                disclosure = entry.cloud_disclosure
                ledger.authorize_cloud_egress(
                    grant_ids=entry.grant_ids,
                    provider_id=disclosure.provider_id,
                    data_classes=disclosure.data_classes,
                    territory=context.territory,
                    retention_days=disclosure.retention_ceiling_days,
                    at_iso=at_iso,
                    context=context,
                )
        except AuthorizationError:
            logger.warning("cache reuse authorization denied")
            self.evict_asset(entry.artifact_id)
            raise _error("cache authorization was denied", "cache_authorization_denied") from None

    def reuse(
        self,
        fingerprint: RenderFingerprint,
        stage_cue_id: str,
        *,
        ledger: _Ledger,
        context: AuthorizationContext,
        at_iso: str,
    ) -> CacheEntry:
        """Recompute the key, validate integrity, then reauthorize immediately."""

        _require_complete(fingerprint)
        try:
            stage_cue_id = BoundedCode(stage_cue_id)
        except (TypeError, ValueError):
            raise _error("cache identity is invalid", "invalid_cache_identity") from None
        key = fingerprint.cache_key(stage_cue_id)
        entry = self._entries.get(key)
        if entry is None:
            raise _error("cache entry was not found", "cache_miss")
        self._validate_hit(entry, key, fingerprint, stage_cue_id)
        self._authorize_hit(entry, ledger, context, at_iso)
        return entry

    def evict_asset(self, artifact_id: str) -> int:
        """Evict every stage/cue alias for one opaque artifact id."""

        try:
            artifact_id = BoundedCode(artifact_id)
        except (TypeError, ValueError):
            raise _error("cache artifact id is invalid", "invalid_cache_identity") from None
        keys = tuple(key for key, entry in self._entries.items() if entry.artifact_id == artifact_id)
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
