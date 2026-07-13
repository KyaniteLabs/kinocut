"""Adversarial S2 fail-closed authorization hardening tests."""

from __future__ import annotations

from threading import Event, Thread

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
    CloudEgressGrant,
    ConsentGrant,
    ConsentScope,
    ConsentState,
    RetentionPolicy,
)


_SHA = "sha256:" + "c" * 64
_NOW = "2026-07-13T12:00:00Z"
_CONTEXT = AuthorizationContext(operation="voice_clone", provider_class="local", territory="US")


def _grant(
    grant_id: str,
    *,
    operations: tuple[str, ...] = ("voice_clone",),
    retention: str = "quarantine_on_revocation",
    cloud: CloudEgressGrant | None = None,
) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id=f"subject_{grant_id}",
        rightsholder_id=f"rights_{grant_id}",
        scope=ConsentScope(
            project_ids=("project_alpha",),
            character_ids=("character_a",),
            operations=operations,
            provider_classes=("local", "cloud"),
            territory="US",
        ),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(
            biometric_retention=retention,
            audit_retention="keep_5y",
        ),
        cloud_egress=cloud,
    )


def _register(ledger: ConsentLedger, *grants: ConsentGrant) -> None:
    for grant in grants:
        ledger.register_grant(grant, at_iso=_NOW, actor_id="reviewer_001")


def test_unknown_revocation_policy_is_rejected_without_state_change() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.revoke(
            "grant_a",
            expected_state=ConsentState.LIVE,
            policy="unknown",  # type: ignore[arg-type]
            at_iso="2026-07-13T12:00:01Z",
            actor_id="reviewer_001",
        )
    assert exc_info.value.code == "invalid_revocation_policy"
    assert ledger.current_grant("grant_a").state is ConsentState.LIVE


def test_requested_scope_must_be_authorized_by_every_grant() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))

    hostile = AuthorizationContext(
        operation="voice_impersonate",
        project_id="project_other",
        character_id="character_other",
        provider_class="cloud",
        territory="GB",
    )
    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize(
            AuthorizationBoundary.GENERATION,
            grant_ids=("grant_a",),
            context=hostile,
            at_iso=_NOW,
        )
    assert exc_info.value.code == "grant_scope_denied"


def test_empty_cloud_egress_grants_or_data_classes_fail_closed() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    cloud = CloudEgressGrant(
        provider_id="provider_alpha",
        data_classes=("reference_audio",),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso="2027-01-01T00:00:00Z",
    )
    _register(ledger, _grant("grant_a", cloud=cloud))

    requests = (
        dict(grant_ids=(), data_classes=("reference_audio",)),
        dict(grant_ids=("grant_a",), data_classes=()),
    )
    for request in requests:
        with pytest.raises(AuthorizationError) as exc_info:
            ledger.authorize_cloud_egress(
                provider_id="provider_alpha",
                territory="US",
                retention_days=30,
                context=_CONTEXT,
                at_iso=_NOW,
                **request,
            )
        assert exc_info.value.code == "cloud_egress_denied"


def test_commit_reauthorizes_transitive_parent_lineage() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_parent"), _grant("grant_new"))
    ledger.record_asset(
        "asset_parent",
        direct_grant_ids=("grant_parent",),
        parent_asset_ids=(),
        context=_CONTEXT,
        at_iso=_NOW,
    )
    ledger.acquire_lease(
        "lease_new",
        grant_ids=("grant_new",),
        ttl_seconds=20,
        context=_CONTEXT,
        at_iso="2026-07-13T12:00:01Z",
        actor_id="worker_001",
    )
    ledger.revoke(
        "grant_parent",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.CANCEL,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="reviewer_001",
    )

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.commit_lease(
            "lease_new",
            output_asset_id="asset_child",
            parent_asset_ids=("asset_parent",),
            at_iso="2026-07-13T12:00:03Z",
            actor_id="worker_001",
        )
    assert exc_info.value.code == "grant_revoked"


def test_expired_waiting_lease_finalizes_pending_revocation() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=1,
        context=_CONTEXT,
        at_iso="2026-07-13T12:00:01Z",
        actor_id="worker_001",
    )
    ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.WAIT,
        at_iso="2026-07-13T12:00:01Z",
        actor_id="reviewer_001",
    )

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.commit_lease(
            "lease_a",
            output_asset_id="asset_late",
            parent_asset_ids=(),
            at_iso="2026-07-13T12:00:03Z",
            actor_id="worker_001",
        )
    assert exc_info.value.code == "lease_expired"
    assert ledger.current_grant("grant_a").state is ConsentState.REVOKED


def test_aborted_waiting_lease_finalizes_pending_revocation() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=20,
        context=_CONTEXT,
        at_iso="2026-07-13T12:00:01Z",
        actor_id="worker_001",
    )
    ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.WAIT,
        at_iso="2026-07-13T12:00:02Z",
        actor_id="reviewer_001",
    )

    ledger.abort_lease(
        "lease_a",
        at_iso="2026-07-13T12:00:03Z",
        actor_id="worker_001",
    )
    assert ledger.current_grant("grant_a").state is ConsentState.REVOKED


def test_delete_outcome_cannot_be_downgraded_by_later_quarantine() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(
        ledger,
        _grant("grant_delete", retention="delete_on_revocation"),
        _grant("grant_quarantine"),
    )
    ledger.record_asset(
        "asset_blend",
        direct_grant_ids=("grant_delete", "grant_quarantine"),
        parent_asset_ids=(),
        context=_CONTEXT,
        at_iso=_NOW,
    )
    for grant_id in ("grant_delete", "grant_quarantine"):
        ledger.revoke(
            grant_id,
            expected_state=ConsentState.LIVE,
            policy=RevocationPolicy.CANCEL,
            at_iso="2026-07-13T12:00:05Z",
            actor_id="reviewer_001",
        )
    assert ledger.outcome_for("asset_blend").disposition is DerivativeDisposition.DELETE


def test_acquire_and_revoke_are_serialized(monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))
    entered = Event()
    release = Event()
    revoked = Event()
    original = ledger._authorize_grants

    def paused(*args, **kwargs):
        entered.set()
        assert release.wait(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "_authorize_grants", paused)
    acquire = Thread(
        target=ledger.acquire_lease,
        args=("lease_a",),
        kwargs=dict(
            grant_ids=("grant_a",),
            ttl_seconds=20,
            context=_CONTEXT,
            at_iso="2026-07-13T12:00:01Z",
            actor_id="worker_001",
        ),
    )
    revoke = Thread(
        target=lambda: (
            ledger.revoke(
                "grant_a",
                expected_state=ConsentState.LIVE,
                policy=RevocationPolicy.CANCEL,
                at_iso="2026-07-13T12:00:02Z",
                actor_id="reviewer_001",
            ),
            revoked.set(),
        )
    )
    acquire.start()
    assert entered.wait(2)
    revoke.start()
    assert not revoked.wait(0.05)
    release.set()
    acquire.join(2)
    revoke.join(2)
    assert revoked.is_set()
    with pytest.raises(AuthorizationError) as exc_info:
        ledger.commit_lease(
            "lease_a",
            output_asset_id="asset_late",
            parent_asset_ids=(),
            at_iso="2026-07-13T12:00:03Z",
            actor_id="worker_001",
        )
    assert exc_info.value.code == "lease_cancelled"
