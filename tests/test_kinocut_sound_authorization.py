"""RED-first S2 authorization runtime tests."""

from __future__ import annotations

import pytest

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
)
from kinocut_sound.consent import ConsentGrant, ConsentScope, ConsentState, RetentionPolicy


_CONTEXT = AuthorizationContext(operation="voice_clone", provider_class="local", territory="US")
_SHA = "sha256:" + "a" * 64


def _grant(grant_id: str) -> ConsentGrant:
    return ConsentGrant(
        grant_id=grant_id,
        subject_id="subject_opaque",
        rightsholder_id="rights_opaque",
        scope=ConsentScope(
            operations=("voice_clone",),
            provider_classes=("local",),
            territory="US",
        ),
        reference_evidence_hash=_SHA,
        transcript_evidence_hash=_SHA,
        reviewer_id="reviewer_001",
        issue_iso="2026-01-01T00:00:00Z",
        expiry_iso="2027-01-01T00:00:00Z",
        state=ConsentState.LIVE,
        retention=RetentionPolicy(
            biometric_retention="quarantine_on_revocation",
            audit_retention="keep_5y",
        ),
    )


def test_missing_grant_fails_closed_at_export() -> None:
    ledger = ConsentLedger(max_lease_seconds=60)

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize(
            AuthorizationBoundary.EXPORT,
            grant_ids=("grant_missing",),
            context=_CONTEXT,
            at_iso="2026-07-13T12:00:00Z",
        )
    assert exc_info.value.code == "grant_missing"


def test_ledger_event_excludes_subject_and_host_data() -> None:
    ledger = ConsentLedger(max_lease_seconds=60)
    ledger.register_grant(
        _grant("grant_a"),
        at_iso="2026-07-13T12:00:00Z",
        actor_id="reviewer_001",
    )

    payload = ledger.events[0].to_dict()
    assert "subject_id" not in payload
    assert "/home/" not in repr(payload)
