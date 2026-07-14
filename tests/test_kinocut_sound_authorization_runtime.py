"""Focused S2 revocation-race, lineage, and egress tests."""

from __future__ import annotations

import pytest

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
    DerivativeDisposition,
    RevocationPolicy,
)
from kinocut_sound.consent import (
    BlendAuthorization,
    CloudEgressGrant,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)


_SHA = "sha256:" + "b" * 64
_NOW = "2026-07-13T12:00:00Z"
_CONTEXT = AuthorizationContext(operation="voice_clone", provider_class="local", territory="US")
_BLEND_CONTEXT = AuthorizationContext(operation="voice_blend", provider_class="local", territory="US")


def _grant(
    grant_id: str,
    *,
    state: ConsentState = ConsentState.LIVE,
    expiry_iso: str = "2027-01-01T00:00:00Z",
    blend: BlendAuthorization | None = None,
    cloud: CloudEgressGrant | None = None,
    retention: str = "quarantine_on_revocation",
) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id=f"subject_{grant_id}",
        rightsholder_id=f"rights_{grant_id}",
        scope=ConsentScope(
            operations=("voice_clone", "voice_blend"),
            provider_classes=("local", "cloud"),
            territory="US",
        ),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso=expiry_iso,
        state=state,
        retention=RetentionPolicy(
            biometric_retention=retention,
            audit_retention="keep_5y",
        ),
        blend=blend,
        cloud_egress=cloud,
    )


@pytest.mark.parametrize(
    "boundary",
    [
        AuthorizationBoundary.CACHE_REUSE,
        AuthorizationBoundary.ASSEMBLY,
        AuthorizationBoundary.EXPORT,
    ],
)
@pytest.mark.parametrize(
    ("grant", "code"),
    [
        (_grant("grant_expired", expiry_iso="2026-02-01T00:00:00Z"), "grant_expired"),
        (_grant("grant_revoked", state=ConsentState.REVOKED), "grant_revoked"),
    ],
)
def test_every_reuse_boundary_reauthorizes_expiry_and_revocation(
    boundary: AuthorizationBoundary,
    grant: ConsentGrant,
    code: str,
) -> None:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(grant, at_iso="2026-01-15T00:00:00Z", actor_id="reviewer_001")

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize(boundary, grant_ids=(grant.grant_id,), context=_CONTEXT, at_iso=_NOW)
    assert exc_info.value.code == code


def test_compare_before_replace_rejects_stale_state() -> None:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.revoke(
            "grant_a",
            expected_state=ConsentState.EXPIRED,
            policy=RevocationPolicy.CANCEL,
            at_iso="2026-07-13T12:00:01Z",
            actor_id="reviewer_001",
        )
    assert exc_info.value.code == "consent_state_conflict"
    assert ledger.current_grant("grant_a").state is ConsentState.LIVE


def test_wait_revocation_blocks_new_lease_and_rechecks_before_commit() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    lease = ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=20,
        context=_CONTEXT,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="worker_001",
    )
    result = ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.WAIT,
        at_iso="2026-07-13T12:00:03Z",
        actor_id="reviewer_001",
    )
    assert result.pending
    with pytest.raises(AuthorizationError) as exc_info:
        ledger.acquire_lease(
            "lease_b",
            grant_ids=("grant_a",),
            ttl_seconds=20,
            context=_CONTEXT,
            at_iso="2026-07-13T12:00:04Z",
            actor_id="worker_002",
        )
    assert exc_info.value.code == "revocation_pending"

    lineage = ledger.commit_lease(
        lease.lease_id,
        output_asset_id="asset_clip",
        parent_asset_ids=(),
        at_iso="2026-07-13T12:00:05Z",
        actor_id="worker_001",
    )
    assert lineage.direct_grant_ids == ("grant_a",)
    assert ledger.current_grant("grant_a").state is ConsentState.REVOKED
    assert ledger.outcome_for("asset_clip").disposition is DerivativeDisposition.QUARANTINE


def test_cancel_revocation_cancels_inflight_and_precommit_fails_closed() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=20,
        context=_CONTEXT,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="worker_001",
    )
    result = ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.CANCEL,
        at_iso="2026-07-13T12:00:03Z",
        actor_id="reviewer_001",
    )
    assert result.cancelled_lease_ids == ("lease_a",)

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.commit_lease(
            "lease_a",
            output_asset_id="asset_clip",
            parent_asset_ids=(),
            at_iso="2026-07-13T12:00:04Z",
            actor_id="worker_001",
        )
    assert exc_info.value.code == "lease_cancelled"


def test_transitive_lineage_deletes_every_reachable_derivative() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    ledger.register_grant(
        _grant("grant_a", retention="delete_on_revocation"),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    ledger.record_asset("asset_clip", direct_grant_ids=("grant_a",), parent_asset_ids=(), context=_CONTEXT, at_iso=_NOW)
    ledger.record_asset(
        "asset_stem", direct_grant_ids=(), parent_asset_ids=("asset_clip",), context=_CONTEXT, at_iso=_NOW
    )
    ledger.record_asset(
        "asset_mix", direct_grant_ids=(), parent_asset_ids=("asset_stem",), context=_CONTEXT, at_iso=_NOW
    )
    assert ledger.resolve_grants("asset_mix") == ("grant_a",)

    ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.CANCEL,
        at_iso="2026-07-13T12:00:10Z",
        actor_id="reviewer_001",
    )
    assert {ledger.outcome_for(asset_id).disposition for asset_id in ("asset_clip", "asset_stem", "asset_mix")} == {
        DerivativeDisposition.DELETE
    }
    with pytest.raises(AuthorizationError):
        ledger.authorize(
            AuthorizationBoundary.EXPORT,
            asset_ids=("asset_mix",),
            context=_CONTEXT,
            at_iso="2026-07-13T12:00:11Z",
        )


def test_blend_and_cloud_egress_require_each_exact_grant_scope() -> None:
    cloud = CloudEgressGrant(
        provider_id="provider_alpha",
        data_classes=("reference_audio", "transcript"),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso="2027-01-01T00:00:00Z",
    )
    ledger = ConsentLedger(max_lease_seconds=30)
    ledger.register_grant(_grant("grant_a", cloud=cloud), at_iso=_NOW, actor_id="reviewer_001")
    ledger.register_grant(_grant("grant_b", cloud=cloud), at_iso=_NOW, actor_id="reviewer_001")
    ledger.register_grant(
        _grant(
            "grant_blend",
            blend=BlendAuthorization(
                source_grant_ids=("grant_a", "grant_b"),
                composite_subject_id="subject_blend",
            ),
        ),
        at_iso=_NOW,
        actor_id="reviewer_001",
    )
    assert ledger.authorize_blend("grant_blend", context=_BLEND_CONTEXT, at_iso=_NOW) == (
        "grant_a",
        "grant_b",
        "grant_blend",
    )
    ledger.authorize_cloud_egress(
        grant_ids=("grant_a", "grant_b"),
        provider_id="provider_alpha",
        data_classes=("reference_audio",),
        territory="US",
        retention_days=30,
        context=AuthorizationContext(operation="voice_clone", provider_class="cloud", territory="US"),
        at_iso=_NOW,
    )

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize_cloud_egress(
            grant_ids=("grant_a", "grant_b"),
            provider_id="provider_alpha",
            data_classes=("embedding",),
            territory="US",
            retention_days=30,
            context=AuthorizationContext(operation="voice_clone", provider_class="cloud", territory="US"),
            at_iso=_NOW,
        )
    assert exc_info.value.code == "cloud_egress_denied"

    ledger.revoke(
        "grant_b",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.CANCEL,
        at_iso="2026-07-13T12:00:10Z",
        actor_id="reviewer_001",
    )
    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize_blend(
            "grant_blend",
            context=_BLEND_CONTEXT,
            at_iso="2026-07-13T12:00:11Z",
        )
    assert exc_info.value.code == "grant_revoked"
