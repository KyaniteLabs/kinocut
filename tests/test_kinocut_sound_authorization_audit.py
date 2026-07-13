"""Hostile audit-binding tests for S2 sound authorization."""

from __future__ import annotations

import pytest

from kinocut_sound.authorization import (
    AuthorizationBoundary,
    AuthorizationContext,
    AuthorizationError,
    ConsentLedger,
)
from kinocut_sound.consent import BlendAuthorization, CloudEgressGrant
from tests.test_kinocut_sound_authorization_hardening import _CONTEXT, _NOW, _grant, _register


def test_boundary_audit_hash_binds_complete_context_without_raw_values() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    grant = _grant("grant_a").model_copy(
        update={
            "scope": _grant("scope_template").scope.model_copy(
                update={"project_ids": ("project_alpha", "project_beta")}
            )
        }
    )
    _register(ledger, grant)
    second_context = AuthorizationContext(
        operation="voice_clone",
        project_id="project_beta",
        character_id="character_a",
        provider_class="local",
        territory="US",
    )

    for context in (_CONTEXT, second_context):
        ledger.authorize(
            AuthorizationBoundary.GENERATION,
            grant_ids=("grant_a",),
            context=context,
            at_iso=_NOW,
        )

    events = [event for event in ledger.events if event.event == "boundary_authorized"]
    assert events[0].detail_hash != events[1].detail_hash
    assert "project_alpha" not in repr(events[0].to_dict())


def test_blend_authorization_appends_privacy_safe_audit_event() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    source_a = _grant("grant_a", operations=("voice_blend",))
    source_b = _grant("grant_b", operations=("voice_blend",))
    composite = _grant("grant_blend", operations=("voice_blend",)).model_copy(
        update={
            "blend": BlendAuthorization(
                source_grant_ids=("grant_a", "grant_b"),
                composite_subject_id="subject_blend",
            )
        }
    )
    _register(ledger, source_a, source_b, composite)
    context = AuthorizationContext(
        operation="voice_blend",
        project_id="project_alpha",
        character_id="character_a",
        provider_class="local",
        territory="US",
    )

    ledger.authorize_blend("grant_blend", context=context, at_iso=_NOW)

    event = ledger.events[-1]
    assert event.event == "blend_authorized"
    assert event.detail_hash is not None
    assert "project_alpha" not in repr(event.to_dict())


def test_blend_rejects_untyped_context_with_custom_error() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    _register(ledger, _grant("grant_a"))

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize_blend("grant_a", context=object(), at_iso=_NOW)  # type: ignore[arg-type]
    assert exc_info.value.code == "grant_scope_invalid"


def test_cloud_egress_rejects_local_provider_context() -> None:
    ledger = ConsentLedger(max_lease_seconds=30)
    cloud = CloudEgressGrant(
        provider_id="provider_alpha",
        data_classes=("reference_audio",),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso="2027-01-01T00:00:00Z",
    )
    _register(ledger, _grant("grant_a", cloud=cloud))

    with pytest.raises(AuthorizationError) as exc_info:
        ledger.authorize_cloud_egress(
            grant_ids=("grant_a",),
            provider_id="provider_alpha",
            data_classes=("reference_audio",),
            territory="US",
            retention_days=30,
            at_iso=_NOW,
            context=_CONTEXT,
        )
    assert exc_info.value.code == "grant_scope_denied"


def _context_bound_event_hashes(project_id: str) -> dict[str, str | None]:
    ledger = ConsentLedger(max_lease_seconds=30)
    cloud = CloudEgressGrant(
        provider_id="provider_alpha",
        data_classes=("reference_audio",),
        territory="US",
        retention_ceiling_days=30,
        expiry_iso="2027-01-01T00:00:00Z",
    )
    grant = _grant("grant_a", cloud=cloud).model_copy(
        update={
            "scope": _grant("scope_template").scope.model_copy(
                update={"project_ids": ("project_alpha", "project_beta")}
            )
        }
    )
    _register(ledger, grant)
    context = AuthorizationContext(
        operation="voice_clone",
        project_id=project_id,
        character_id="character_a",
        provider_class="cloud",
        territory="US",
    )
    ledger.acquire_lease(
        "lease_a",
        grant_ids=("grant_a",),
        ttl_seconds=10,
        context=context,
        at_iso=_NOW,
        actor_id="worker_001",
    )
    ledger.commit_lease(
        "lease_a",
        output_asset_id="asset_lease",
        parent_asset_ids=(),
        at_iso="2026-07-13T12:00:01Z",
        actor_id="worker_001",
    )
    ledger.record_asset(
        "asset_record",
        direct_grant_ids=("grant_a",),
        parent_asset_ids=(),
        context=context,
        at_iso="2026-07-13T12:00:02Z",
    )
    ledger.authorize_cloud_egress(
        grant_ids=("grant_a",),
        provider_id="provider_alpha",
        data_classes=("reference_audio",),
        territory="US",
        retention_days=30,
        at_iso="2026-07-13T12:00:03Z",
        context=context,
    )
    names = {
        "lease_acquired",
        "lease_committed",
        "asset_committed",
        "asset_lineage_recorded",
        "cloud_egress_authorized",
    }
    return {event.event: event.detail_hash for event in ledger.events if event.event in names}


def test_lease_lineage_and_cloud_audit_hashes_bind_complete_context() -> None:
    alpha = _context_bound_event_hashes("project_alpha")
    beta = _context_bound_event_hashes("project_beta")

    assert alpha.keys() == beta.keys()
    assert all(alpha[name] != beta[name] for name in alpha)
