"""Consent ledger and delivery-policy regressions (roast audit C-08, C-09, C-10, C-11).

An empty ``operations`` list meant "every operation". The decision time was
whatever ``at_iso`` the caller passed, so an expired grant authorized with an
earlier timestamp. A misspelled retention code silently meant "keep", and the
legitimate ``delete`` code was not in the policy's delete set at all. A named
delivery preset was stored but never applied to the loudness gate.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
    DerivativeDisposition,
    RevocationPolicy,
)
from kinocut_sound.consent import ConsentGrant, ConsentScope, ConsentState, RetentionPolicy
from kinocut_sound.delivery import DeliveryPolicy, DeliveryPreset, LoudnessTarget

_NOW = "2026-07-13T12:00:00Z"
_SHA = "sha256:" + "a" * 64
_CONTEXT = AuthorizationContext(operation="voice_clone", provider_class="local", territory="US")


def _grant(
    grant_id: str, *, scope: ConsentScope | None = None, retention: str = "quarantine_on_revocation"
) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id=f"subject_{grant_id}",
        rightsholder_id=f"rights_{grant_id}",
        scope=scope or ConsentScope(operations=("voice_clone",), territory="US"),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(biometric_retention=retention, audit_retention="keep_5y"),
    )


# --- C-09: empty scope is not a wildcard ---------------------------------------


def test_grant_that_names_no_operations_authorizes_nothing() -> None:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(_grant("grant_a", scope=ConsentScope(territory="US")), at_iso=_NOW, actor_id="reviewer_001")

    with pytest.raises(AuthorizationError) as denied:
        ledger.authorize(
            AuthorizationBoundary.EXPORT,
            grant_ids=("grant_a",),
            context=AuthorizationContext(operation="export_everything", territory="US"),
            at_iso=_NOW,
        )
    assert denied.value.code == "grant_scope_invalid"


def test_named_operations_still_authorize_within_scope() -> None:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.authorize(AuthorizationBoundary.EXPORT, grant_ids=("grant_a",), context=_CONTEXT, at_iso=_NOW)


# --- C-10: decision time must not be the caller's alone ------------------------


def test_trusted_clock_blocks_replaying_an_expired_grant_with_an_earlier_time() -> None:
    expired_june = _grant("grant_a")
    ledger = ConsentLedger(max_lease_seconds=60, clock=lambda: "2026-11-01T00:00:00Z")
    ledger.register_grant(
        expired_june.model_copy(update={"expiry_iso": "2026-06-01T00:00:00Z"}),
        at_iso="2026-03-01T00:00:00Z",
        actor_id="reviewer_001",
    )

    with pytest.raises(AuthorizationError) as expired:
        # March is before the expiry, but the trusted clock says November.
        ledger.authorize(
            AuthorizationBoundary.EXPORT, grant_ids=("grant_a",), context=_CONTEXT, at_iso="2026-03-01T00:00:00Z"
        )
    assert expired.value.code == "grant_expired"


def test_trusted_clock_never_moves_decision_time_backwards() -> None:
    ledger = ConsentLedger(max_lease_seconds=60, clock=lambda: _NOW)
    ledger.register_grant(_grant("grant_a"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.authorize(
        AuthorizationBoundary.EXPORT, grant_ids=("grant_a",), context=_CONTEXT, at_iso="2026-08-01T00:00:00Z"
    )


# --- C-11: retention codes are a closed vocabulary -----------------------------


def test_misspelled_retention_code_is_rejected_instead_of_meaning_keep() -> None:
    with pytest.raises(ValidationError):
        RetentionPolicy(biometric_retention="delete_on_revoke", audit_retention="keep_5y")


def test_delete_retention_code_deletes_derivatives_on_revocation() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    ledger.register_grant(_grant("grant_a", retention="delete"), at_iso=_NOW, actor_id="reviewer_001")
    ledger.record_asset("asset_clip", direct_grant_ids=("grant_a",), parent_asset_ids=(), context=_CONTEXT, at_iso=_NOW)

    ledger.revoke(
        "grant_a",
        expected_state=ConsentState.LIVE,
        policy=RevocationPolicy.CANCEL,
        at_iso=_NOW,
        actor_id="reviewer_001",
    )

    # "delete" was not in the policy's delete set, so this used to quarantine.
    assert ledger.outcome_for("asset_clip").disposition is DerivativeDisposition.DELETE


# --- C-08: the preset drives the gate ------------------------------------------


def test_delivery_preset_drives_loudness_and_true_peak_ceiling() -> None:
    policy = DeliveryPolicy(preset=DeliveryPreset.BROADCAST_EBU_R128_MINUS_23)
    assert policy.loudness.integrated_lufs == -23.0
    assert policy.loudness.true_peak_dbtp == -2.0
    assert policy.true_peak_ceiling_dbtp == -2.0


def test_explicit_delivery_values_still_win_over_the_preset() -> None:
    policy = DeliveryPolicy(
        preset=DeliveryPreset.BROADCAST_EBU_R128_MINUS_23,
        loudness=LoudnessTarget(integrated_lufs=-18, true_peak_dbtp=-2),
        true_peak_ceiling_dbtp=-3,
    )
    assert policy.loudness.integrated_lufs == -18.0
    assert policy.true_peak_ceiling_dbtp == -3


def test_default_delivery_policy_is_unchanged() -> None:
    policy = DeliveryPolicy()
    assert policy.preset is DeliveryPreset.STREAM_MINUS_14
    assert policy.loudness.integrated_lufs == -14.0
    assert policy.true_peak_ceiling_dbtp == -1.0
