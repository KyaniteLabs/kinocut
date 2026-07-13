"""Strict hostile tests for final S2 authorization closure."""

from __future__ import annotations

from threading import Event, Thread

import pytest

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationError,
    ConsentLedger,
    RevocationPolicy,
)
from kinocut_sound.consent import BlendAuthorization, ConsentState
from tests.test_kinocut_sound_authorization_hardening import _CONTEXT, _NOW, _grant, _register


def test_protected_boundary_rejects_missing_scope_context() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize(
            AuthorizationBoundary.GENERATION,
            grant_ids=("grant_a",),
            at_iso=_NOW,
        )
    assert exc_info.value.code == "grant_scope_missing"


def test_blend_requires_voice_blend_operation_on_every_grant() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    source_a = _grant("grant_a", operations=("voice_clone",))
    source_b = _grant("grant_b", operations=("voice_clone",))
    composite = _grant("grant_blend", operations=("voice_clone",)).model_copy(
        update={
            "blend": BlendAuthorization(
                source_grant_ids=("grant_a", "grant_b"),
                composite_subject_id="subject_blend",
            )
        }
    )
    _register(ledger, source_a, source_b, composite)

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize_blend("grant_blend", at_iso=_NOW)
    assert exc_info.value.code == "grant_scope_denied"


def test_invalid_calendar_grant_expiry_fails_closed_at_registration() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    malformed = _grant("grant_bad").model_copy(
        update={"expiry_iso": "2027-99-99T99:99:99Z"}
    )

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.register_grant(malformed, at_iso=_NOW, actor_id="reviewer_001")
    assert exc_info.value.code == "invalid_timestamp"


def test_record_asset_and_revoke_are_one_atomic_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    record = Thread(
        target=ledger.record_asset,
        args=("asset_late",),
        kwargs=dict(
            direct_grant_ids=("grant_a",),
            parent_asset_ids=(),
            context=_CONTEXT,
            at_iso="2026-07-13T12:00:01Z",
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
    record.start()
    assert entered.wait(2)
    revoke.start()
    assert not revoked.wait(0.05)
    release.set()
    record.join(2)
    revoke.join(2)
    assert revoked.is_set()
    assert ledger.outcome_for("asset_late").grant_id == "grant_a"


def test_wait_expiry_emits_exactly_one_expired_event() -> None:
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

    with pytest.raises(AuthorizationError):
        ledger.commit_lease(
            "lease_a",
            output_asset_id="asset_late",
            parent_asset_ids=(),
            at_iso="2026-07-13T12:00:03Z",
            actor_id="worker_001",
        )
    assert [event.event for event in ledger.events].count("lease_expired") == 1

